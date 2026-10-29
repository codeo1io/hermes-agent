"""Tests for #94895: gateway-side heartbeat refresher wiring.

The startup orphan sweep now consults ``gateway_heartbeats`` to tell
"row owned by another live backend" from "row truly orphaned".  Each
serve / TUI-gateway process registers a heartbeat row at startup and
refreshes it periodically.  This file verifies:

* The refresher registers a row on first call and is once-per-process.
* ``entry.main`` and ``ws.handle_ws`` both call it (mirroring the
  existing orphan-sweep wiring pattern).
* Failure to start the refresher is swallowed so a malformed DB
  never breaks gateway startup.
* ``HERMES_GATEWAY_HEARTBEAT_REFRESH_S=0`` disables the refresher.
* A backend that crashed without ``atexit`` (SIGKILL, OOM, hard crash)
  has its row reclaimed by the prune that runs inside every heartbeat
  refresh once the row crosses the prune age.
"""

from __future__ import annotations

import io
import time

import pytest

from hermes_state import SessionDB
from hermes_cli import model_switch_providers


IDLE_S = 6 * 3600


@pytest.fixture
def db(tmp_path):
    return SessionDB(tmp_path / "state.db")


class TestBackendHeartbeatRefresher:
    def test_first_call_registers_row_in_db(self, db, monkeypatch, tmp_path):
        from tui_gateway import server

        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", 0.0)  # never re-enter
        # Reset the once-per-process guard so the test runs cleanly.
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)
        # Use a stable backend id for assertion.
        monkeypatch.setattr(
            server, "_backend_id_for_this_process",
            lambda: "test-backend-A",
        )

        server._start_backend_heartbeat_refresher()

        rows = db.list_backend_heartbeats()
        assert len(rows) == 1
        assert rows[0]["backend_id"] == "test-backend-A"
        assert rows[0]["last_heartbeat"] > 0

    def test_repeat_calls_are_noops(self, db, monkeypatch):
        from tui_gateway import server

        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", 0.0)
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)
        monkeypatch.setattr(
            server, "_backend_id_for_this_process",
            lambda: "test-backend-A",
        )

        server._start_backend_heartbeat_refresher()
        server._start_backend_heartbeat_refresher()
        server._start_backend_heartbeat_refresher()

        rows = db.list_backend_heartbeats()
        assert len(rows) == 1

        # Should have written the initial row exactly once, no thread started.
        # (The default flow with _HEARTBEAT_REFRESH_S > 0 would spawn a
        # thread; we asserted the helper is a no-op for repeat calls above.)

    def test_refresher_failure_does_not_raise(self, monkeypatch):
        """A malformed DB / write error must never break startup."""
        from tui_gateway import server

        def _boom():
            raise RuntimeError("disk full")

        monkeypatch.setattr(server, "_refresh_backend_heartbeat", _boom)
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", 0.0)
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)

        # Must not raise.
        server._start_backend_heartbeat_refresher()


class TestCrashResidueReclaim:
    """The crash-recovery leg of the heartbeat lifecycle.

    A backend that dies without running ``atexit`` (SIGKILL after the
    supervisor grace, OOM, hard crash) leaks its heartbeat row forever —
    the startup orphan sweep then keeps treating the dead backend's idle
    sessions as live-owned. The fix: every heartbeat refresh (the
    synchronous startup registration and each loop tick) prunes rows
    older than ``_HEARTBEAT_PRUNE_AGE_S``.
    """

    @staticmethod
    def _seed(db, backend_id, age_s):
        now = time.time()
        db.register_backend_heartbeat(
            backend_id=backend_id, pid=1, started_at=now - age_s - 60,
            last_heartbeat=now - age_s, profile="p", host="h")

    def test_refresh_reclaims_crashed_backend_row(self, db, monkeypatch):
        """THE regression: a stale crash row is gone after one refresh by a live backend."""
        from tui_gateway import server

        self._seed(db, "crashed@h:1:dead", age_s=3600.0)
        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_backend_id_for_this_process", lambda: "live@h:2:alive")

        server._refresh_backend_heartbeat()

        ids = [r["backend_id"] for r in db.list_backend_heartbeats()]
        assert ids == ["live@h:2:alive"]

    def test_startup_registration_reclaims_crashed_backend_row(self, db, monkeypatch):
        """Restart-after-crash: the synchronous first refresh reclaims residue immediately."""
        from tui_gateway import server

        self._seed(db, "crashed@h:1:dead", age_s=3600.0)
        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_backend_id_for_this_process", lambda: "live@h:2:alive")
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", 0.0)  # no refresher thread
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)

        server._start_backend_heartbeat_refresher()

        ids = [r["backend_id"] for r in db.list_backend_heartbeats()]
        assert ids == ["live@h:2:alive"]

    def test_refresh_prunes_boundary_around_prune_age(self, db, monkeypatch):
        """Liveness safety: rows under the prune age survive a sibling refresh; rows past it go."""
        from tui_gateway import server

        self._seed(db, "stalled@h:3:young", age_s=9.0)
        self._seed(db, "crashed@h:4:old", age_s=11.0)
        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_backend_id_for_this_process", lambda: "live@h:2:alive")
        monkeypatch.setattr(server, "_HEARTBEAT_PRUNE_AGE_S", 10.0)

        server._refresh_backend_heartbeat()

        ids = {r["backend_id"] for r in db.list_backend_heartbeats()}
        assert ids == {"stalled@h:3:young", "live@h:2:alive"}

    def test_prune_age_scales_with_refresh_interval(self):
        """Contract: the crash-residue tolerance is 5 refresh cycles at import defaults."""
        from tui_gateway import server

        assert server._HEARTBEAT_PRUNE_AGE_S == 5.0 * server._HEARTBEAT_REFRESH_S


class TestEntryAndWsWiring:
    """The orphan-sweep wiring pattern (entry.main + handle_ws) extends
    to the heartbeat refresher: both sites must call the start helper."""

    def test_entry_main_starts_heartbeat_refresher(self, monkeypatch):
        from tui_gateway import entry, server

        started = {"n": 0}

        def _start():
            started["n"] += 1

        monkeypatch.setattr(server, "_start_backend_heartbeat_refresher", _start)
        monkeypatch.setattr(entry, "_install_sidecar_publisher", lambda: None)
        monkeypatch.setattr(entry, "ensure_mcp_discovery_started", lambda: None)
        monkeypatch.setattr(entry, "resolve_skin", lambda: "default")
        monkeypatch.setattr(entry.server, "_ensure_skin_watcher", lambda: None)
        monkeypatch.setattr(entry, "_log_exit", lambda reason: None)
        monkeypatch.setattr(entry, "handle_spurious_eof", lambda *a: False)
        monkeypatch.setattr(entry, "write_json", lambda _payload: True)
        monkeypatch.setattr(entry.sys, "stdin", io.StringIO(""))

        monkeypatch.setattr(model_switch_providers, "prewarm_picker_cache_async", lambda: None)

        entry.main()
        assert started["n"] == 1

    def test_handle_ws_starts_heartbeat_refresher(self, monkeypatch):
        import asyncio

        from tui_gateway import server, ws as ws_mod

        started = {"n": 0}
        monkeypatch.setattr(
            server, "_start_backend_heartbeat_refresher",
            lambda: started.__setitem__("n", started["n"] + 1),
        )
        monkeypatch.setattr(server, "resolve_skin", lambda: "default")
        monkeypatch.setattr(server, "_ensure_skin_watcher", lambda: None)
        monkeypatch.setattr(server, "register_live_transport", lambda *_a, **_k: None)
        monkeypatch.setattr(server, "_WS_ORPHAN_REAP_GRACE_S", 0)

        class FakeWS:
            async def accept(self):
                pass

            async def send_text(self, line):
                pass

            async def receive_text(self):
                raise ws_mod._WebSocketDisconnect()

            async def close(self):
                pass

        asyncio.run(ws_mod.handle_ws(FakeWS()))
        assert started["n"] == 1

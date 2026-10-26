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
"""

from __future__ import annotations

import io
import logging
import threading
import time

import pytest

from hermes_state import SessionDB
from hermes_cli import model_switch_providers
from tests.waiting import wait_until


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



class TestStaleTombstonePruning:
    """A backend that dies without an orderly exit (crash, SIGKILL, service restart whose
    ``atexit`` clear never ran) leaves a permanent ``gateway_heartbeats`` tombstone — the maestro
    ``phase1.session.operational`` probe counts each as a violation.  The refresher must prune
    rows older than the reclamation window (``max(900 s, 15 missed refreshes)``) at start and on
    every refresh tick, on every serve / TUI / gateway surface."""

    def _start(self, monkeypatch, db, *, refresh_s=0.0, backend_id="test-backend-A"):
        """Point the refresher at a real per-test store in register-once mode by default."""
        from tui_gateway import server

        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", refresh_s)
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)
        monkeypatch.setattr(server, "_backend_id_for_this_process", lambda: backend_id)
        return server

    def test_start_prunes_predecessor_tombstone_keeps_fresh_rows(self, db, monkeypatch):
        """Refresher start reclaims a predecessor's tombstone (last beat older than the window)
        while a fresh sibling row and this process's own row survive.  Red on a tree without the
        prune wiring: the tombstone stays forever."""
        server = self._start(monkeypatch, db)  # register-once mode: window = max(900, 0) = 900 s
        now = time.time()
        db.register_backend_heartbeat(
            backend_id="dead-predecessor", pid=111, started_at=now - 24 * 3600,
            last_heartbeat=now - 1000, profile="p", host="h")
        db.register_backend_heartbeat(
            backend_id="live-sibling", pid=222, started_at=now - 60,
            last_heartbeat=now, profile="p", host="h")

        server._start_backend_heartbeat_refresher()

        ids = sorted(r["backend_id"] for r in db.list_backend_heartbeats())
        assert ids == ["live-sibling", "test-backend-A"]

    def test_register_once_mode_prunes_without_loop_thread(self, db, monkeypatch):
        """``HERMES_GATEWAY_HEARTBEAT_REFRESH_S=0`` (register once, never refresh): the initial
        prune still runs once — before the early return — and no loop thread is started."""
        server = self._start(monkeypatch, db)  # refresh_s=0 → register-once
        now = time.time()
        db.register_backend_heartbeat(
            backend_id="tombstone", pid=111, started_at=now - 7200,
            last_heartbeat=now - 1000, profile="p", host="h")
        spawned: list[str] = []
        real_thread = threading.Thread

        class _RecordingThread(real_thread):
            def __init__(self, *args, **kwargs):
                spawned.append(str(kwargs.get("name") or args))
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(server.threading, "Thread", _RecordingThread)

        server._start_backend_heartbeat_refresher()

        assert spawned == []  # the loop never starts in register-once mode
        assert [r["backend_id"] for r in db.list_backend_heartbeats()] == ["test-backend-A"]

    def test_refresh_tick_prunes_row_aging_past_window(self, db, monkeypatch):
        """A row that is fresh at start but ages past the window between ticks is reclaimed by
        the loop — not only by the initial synchronous prune."""
        server = self._start(monkeypatch, db, refresh_s=0.05)  # window = max(900, 0.75) = 900 s
        now = time.time()
        db.register_backend_heartbeat(
            backend_id="still-beating", pid=1, started_at=now,
            last_heartbeat=now, profile="p", host="h")

        server._start_backend_heartbeat_refresher()
        assert "still-beating" in {r["backend_id"] for r in db.list_backend_heartbeats()}

        # Age the row past the window after the initial prune already ran.
        db._conn.execute(
            "UPDATE gateway_heartbeats SET last_heartbeat = ? WHERE backend_id = ?",
            (time.time() - 1000, "still-beating"))
        db._conn.commit()

        wait_until(
            lambda: [r["backend_id"] for r in db.list_backend_heartbeats()] == ["test-backend-A"],
            timeout=5.0, interval=0.02, what="refresh tick to reclaim the aged tombstone")
        # Park the daemon loop (no DB → refresh/prune no-op) so it cannot race this test's
        # fixture teardown for the rest of the file's run.
        monkeypatch.setattr(server, "_get_db", lambda: None)

    def test_prune_failure_does_not_break_refresher_start(self, db, monkeypatch, caplog):
        """A failing prune is debug-logged and swallowed: it must not raise out of the refresher
        start nor prevent this process's own registration."""
        server = self._start(monkeypatch, db)

        def _locked(*, max_age_seconds):
            raise RuntimeError("database is locked")

        monkeypatch.setattr(db, "prune_stale_heartbeats", _locked)
        with caplog.at_level(logging.DEBUG, logger="tui_gateway.server"):
            server._start_backend_heartbeat_refresher()  # must not raise

        assert [r["backend_id"] for r in db.list_backend_heartbeats()] == ["test-backend-A"]
        assert any("prune" in rec.message.lower() for rec in caplog.records)

    def test_prune_is_noop_when_db_unavailable(self, monkeypatch):
        """DB unavailable (``_get_db`` → None): the prune is a no-op and raises nothing."""
        from tui_gateway import server

        monkeypatch.setattr(server, "_get_db", lambda: None)
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", 0.0)
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)

        server._start_backend_heartbeat_refresher()  # must not raise


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

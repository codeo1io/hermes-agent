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
* Stale rows from backends that died without exit cleanup (SIGKILL, crash,
  reboot) are reclaimed by live refreshers once past the sweep-staleness
  window (``2 * _SESSION_TTL_S``; 43 200 s fallback when the sweep is
  disabled) — see ``TestStaleHeartbeatReclamation``.
"""

from __future__ import annotations

import io
import threading
import time

import pytest

from hermes_state import SessionDB
from hermes_cli import model_switch_providers


IDLE_S = 6 * 3600
HEARTBEAT_WINDOW_S = 2 * IDLE_S  # sweep-staleness semantics: 2 x session TTL


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



class TestStaleHeartbeatReclamation:
    """A live refresher reclaims heartbeat rows whose writer died without exit cleanup:
    every row with ``last_heartbeat`` older than the sweep-staleness window
    (``2 * _SESSION_TTL_S``, literal 43 200 s when the sweep is disabled) is dropped
    at refresher start and on every refresh tick."""

    @staticmethod
    def _rows(db):
        return {row["backend_id"]: row for row in db.list_backend_heartbeats()}

    @staticmethod
    def _wait_refresher_thread_gone() -> None:
        """Wait out the daemon heartbeat thread so monkeypatch teardown never races a live
        tick (a post-teardown tick would run the REAL refresh against the real DB handle)."""
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not any(t.name == "hermes-gateway-heartbeat" for t in threading.enumerate()):
                return
            time.sleep(0.01)

    def _register_frozen_peer(self, db, *, backend_id="frozen-peer"):
        frozen = time.time() - (HEARTBEAT_WINDOW_S + 3600)  # 13 h — past the 12 h window
        db.register_backend_heartbeat(
            backend_id=backend_id, pid=4194304, started_at=frozen,
            last_heartbeat=frozen, profile="p", host="other-host")

    def test_start_reclaims_frozen_row(self, db, monkeypatch):
        """A frozen row (no live writer, 13 h stale) is reclaimed by the start-time pass."""
        from tui_gateway import server

        self._register_frozen_peer(db)
        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", 0.0)  # register-once
        monkeypatch.setattr(server, "_SESSION_TTL_S", float(IDLE_S))  # window = 12 h
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)
        monkeypatch.setattr(server, "_backend_id_for_this_process", lambda: "test-backend-A")

        server._start_backend_heartbeat_refresher()

        rows = self._rows(db)
        assert "frozen-peer" not in rows
        assert rows["test-backend-A"]["last_heartbeat"] > 0

    def test_fresh_peer_row_survives_reclaim(self, db, monkeypatch):
        """A peer refreshed inside the window is never touched."""
        from tui_gateway import server

        fresh = time.time() - 10.0
        db.register_backend_heartbeat(
            backend_id="fresh-peer", pid=4194305, started_at=fresh - 60,
            last_heartbeat=fresh, profile="p", host="other-host")
        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", 0.0)
        monkeypatch.setattr(server, "_SESSION_TTL_S", float(IDLE_S))
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)
        monkeypatch.setattr(server, "_backend_id_for_this_process", lambda: "test-backend-A")

        server._start_backend_heartbeat_refresher()

        rows = self._rows(db)
        assert set(rows) == {"fresh-peer", "test-backend-A"}
        assert rows["fresh-peer"]["last_heartbeat"] == pytest.approx(fresh)

    def test_register_once_mode_with_sweep_disabled_still_reclaims(self, db, monkeypatch):
        """``_HEARTBEAT_REFRESH_S <= 0`` (register once) still runs the start-time reclaim
        (the call site precedes the early-return), and TTL 0 falls back to the literal
        43 200 s window instead of disabling reclamation."""
        from tui_gateway import server

        self._register_frozen_peer(db)
        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", 0.0)
        monkeypatch.setattr(server, "_SESSION_TTL_S", 0.0)  # sweep off → 43 200 s fallback
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)
        monkeypatch.setattr(server, "_backend_id_for_this_process", lambda: "test-backend-A")

        server._start_backend_heartbeat_refresher()

        rows = self._rows(db)
        assert "frozen-peer" not in rows
        assert "test-backend-A" in rows

    def test_refresh_loop_reclaims_row_inserted_after_start(self, db, monkeypatch):
        """The periodic arm: a row that freezes AFTER this backend started is reclaimed
        by a later refresh tick, not only at start."""
        from tui_gateway import server

        calls = {"n": 0}
        stop = {"flag": False}
        real_refresh = server._refresh_backend_heartbeat

        def _counting_refresh():
            calls["n"] += 1
            if stop["flag"] or calls["n"] > 200:
                # End the daemon thread's lifetime: SystemExit is a BaseException, so
                # the loop's ``except Exception`` does not catch it and the thread ends
                # silently (the test sets ``stop`` once done; 200 is the backstop).
                raise SystemExit
            real_refresh()

        monkeypatch.setattr(server, "_refresh_backend_heartbeat", _counting_refresh)
        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", 0.05)
        monkeypatch.setattr(server, "_SESSION_TTL_S", float(IDLE_S))
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)
        monkeypatch.setattr(server, "_backend_id_for_this_process", lambda: "test-backend-A")
        server._start_backend_heartbeat_refresher()

        # The peer dies mid-life: its row freezes after this backend is already refreshing.
        self._register_frozen_peer(db, backend_id="late-frozen-peer")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if "late-frozen-peer" not in self._rows(db):
                break
            time.sleep(0.05)

        assert "late-frozen-peer" not in self._rows(db), \
            "refresh loop did not reclaim the frozen row within 5 s"
        assert calls["n"] >= 1
        # Kill the refresher thread BEFORE monkeypatch teardown: a later tick would run
        # the real refresh against the real DB handle once the patches are gone.
        stop["flag"] = True
        self._wait_refresher_thread_gone()

    def test_reclaim_failure_does_not_break_refresh_loop(self, db, monkeypatch):
        """The error path's loop leg: a prune that fails on EVERY tick must not kill the
        refresh loop — the own row keeps being maintained (the reclaim helper swallows
        failures exactly like ``_refresh_backend_heartbeat`` does)."""
        from tui_gateway import server

        def _boom(*, max_age_seconds):
            raise RuntimeError("disk full")

        monkeypatch.setattr(db, "prune_stale_heartbeats", _boom)
        calls = {"n": 0}
        stop = {"flag": False}
        real_refresh = server._refresh_backend_heartbeat

        def _counting_refresh():
            calls["n"] += 1
            if stop["flag"] or calls["n"] > 200:
                raise SystemExit
            real_refresh()

        monkeypatch.setattr(server, "_refresh_backend_heartbeat", _counting_refresh)
        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", 0.02)
        monkeypatch.setattr(server, "_SESSION_TTL_S", float(IDLE_S))
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)
        monkeypatch.setattr(server, "_backend_id_for_this_process", lambda: "test-backend-A")
        server._start_backend_heartbeat_refresher()  # must not raise

        self._register_frozen_peer(db)  # something for the failing prune to (not) remove
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and calls["n"] < 5:
            time.sleep(0.02)
        stop["flag"] = True
        self._wait_refresher_thread_gone()

        assert calls["n"] >= 5, "refresh loop stopped ticking after reclaim failures"
        rows = self._rows(db)
        assert "test-backend-A" in rows  # own row maintained through the failures
        assert "frozen-peer" in rows  # the failing prune reclaimed nothing

    def test_reclaim_failure_does_not_break_start(self, db, monkeypatch):
        """A failing prune must never break refresher startup (mirrors
        test_refresher_failure_does_not_raise)."""
        from tui_gateway import server

        def _boom(*, max_age_seconds):
            raise RuntimeError("disk full")

        monkeypatch.setattr(db, "prune_stale_heartbeats", _boom)
        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", 0.0)
        monkeypatch.setattr(server, "_SESSION_TTL_S", float(IDLE_S))
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)
        monkeypatch.setattr(server, "_backend_id_for_this_process", lambda: "test-backend-A")

        server._start_backend_heartbeat_refresher()  # must not raise

        assert "test-backend-A" in self._rows(db)


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

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
        # Keep the starter hermetic: without this the boot reclaim pass would reach for the
        # real launch-home state.db once the reclaim predicate lands.
        monkeypatch.setattr(server, "_reclaim_dead_backend_heartbeat_rows", lambda: None, raising=False)
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", 0.0)
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)

        # Must not raise.
        server._start_backend_heartbeat_refresher()



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


class TestHeartbeatReclaimWiring:
    """Reclaim wiring: the reclaim pass rides the refresher lifecycle — once at boot, after the
    first synchronous own-refresh (even when the refresher is disabled: a register-once
    sidecar still clears a dead predecessor's row before the startup orphan sweep reads the
    table), and once per daemon tick after each refresh, bounding a crashed row's life to
    about one refresh interval.

    These tests pin the WIRING only; the dead-owner fence predicate itself
    (``_reclaim_dead_backend_heartbeat_rows``) is always monkeypatched here."""

    def test_boot_reclaim_runs_after_first_refresh(self, db, monkeypatch):
        from tui_gateway import server

        order: list[str] = []
        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", 0.0)  # register-once sidecar mode
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)
        monkeypatch.setattr(server, "_backend_id_for_this_process", lambda: "wiring-A")
        monkeypatch.setattr(server, "_refresh_backend_heartbeat", lambda: order.append("refresh"))
        monkeypatch.setattr(
            server, "_reclaim_dead_backend_heartbeat_rows", lambda: order.append("reclaim"),
            raising=False)

        server._start_backend_heartbeat_refresher()

        # Own row first, then the reclaim — exactly one of each: interval 0 spawns no thread.
        assert order == ["refresh", "reclaim"]

    def test_tick_runs_reclaim_after_each_refresh(self, db, monkeypatch):
        import threading as threading_mod

        from tui_gateway import server

        order: list[str] = []
        stop_events: list = []
        real_event = threading_mod.Event

        def _captured_event():
            event = real_event()
            stop_events.append(event)
            return event

        # Capture the loop's stop event so the daemon thread can be stopped BEFORE monkeypatch
        # teardown — a leaked tick would run the real refresh against the launch-home state.db.
        monkeypatch.setattr(threading_mod, "Event", _captured_event)
        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", 0.02)
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)
        monkeypatch.setattr(server, "_backend_id_for_this_process", lambda: "wiring-A")
        monkeypatch.setattr(server, "_refresh_backend_heartbeat", lambda: order.append("refresh"))
        monkeypatch.setattr(
            server, "_reclaim_dead_backend_heartbeat_rows", lambda: order.append("reclaim"),
            raising=False)

        server._start_backend_heartbeat_refresher()
        deadline = time.monotonic() + 5.0
        while len(order) < 6 and time.monotonic() < deadline:
            time.sleep(0.005)
        stop_events[0].set()

        # Boot pass plus at least two ticks, and every reclaim directly behind its refresh.
        assert order[:2] == ["refresh", "reclaim"]
        assert order.count("reclaim") >= 3
        assert order[::2] == ["refresh"] * len(order[::2])
        assert order[1::2] == ["reclaim"] * len(order[1::2])

    def test_reclaim_failure_is_swallowed_at_boot_and_in_the_tick(self, db, monkeypatch):
        import threading as threading_mod

        from tui_gateway import server

        def _boom():
            raise RuntimeError("malformed db")

        refreshes = {"n": 0}
        stop_events: list = []
        real_event = threading_mod.Event

        def _captured_event():
            event = real_event()
            stop_events.append(event)
            return event

        monkeypatch.setattr(threading_mod, "Event", _captured_event)
        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", 0.02)
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)
        monkeypatch.setattr(server, "_backend_id_for_this_process", lambda: "wiring-A")
        monkeypatch.setattr(
            server, "_refresh_backend_heartbeat",
            lambda: refreshes.__setitem__("n", refreshes["n"] + 1))
        monkeypatch.setattr(server, "_reclaim_dead_backend_heartbeat_rows", _boom, raising=False)

        # Boot: must not raise despite the failing reclaim pass.
        server._start_backend_heartbeat_refresher()
        deadline = time.monotonic() + 5.0
        while refreshes["n"] < 3 and time.monotonic() < deadline:
            time.sleep(0.005)
        stop_events[0].set()

        # Tick: the refresher thread survives the raising reclaim and keeps refreshing — a
        # dead thread would also stop this process's own heartbeat, the opposite of the fix.
        assert refreshes["n"] >= 3

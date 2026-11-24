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



class TestHeartbeatReclaim:
    """The dead-owner fence of ``_reclaim_dead_backend_heartbeat_rows`` (R1/R2/R4, maestro A4
    finding 34ce45cd2093): same-host rows are reclaimed when their owner is provably gone (dead
    pid at ANY freshness — the crash window; pid reused by a process born after the row's
    owner), a staleness backstop covers alive-but-wedged owners past max(3 × refresh, 180s),
    and foreign-host rows age out only at the sweep's own exemption window (2 × TTL).

    The WIRING (boot + tick) is pinned in ``TestHeartbeatReclaimWiring`` above. These tests run
    the real pass against a real ``SessionDB`` with real child pids — mocks cannot prove the
    fence (the repo's pid-liveness ladder exists precisely because pid semantics are hostile)."""

    def _plant(self, db, backend_id, *, pid, started_at, last_heartbeat, host):
        db.register_backend_heartbeat(
            backend_id=backend_id, pid=pid, started_at=started_at,
            last_heartbeat=last_heartbeat, profile="default", host=host)

    def _server(self, db, monkeypatch, *, own_id="reaper-self", refresh_s=60.0):
        from tui_gateway import server

        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_backend_id_for_this_process", lambda: own_id)
        # Pin the refresh cadence so the same-host bound is exactly max(3 × 60, 180) = 180s.
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", refresh_s)
        return server

    @pytest.mark.platforms("posix")
    def test_reclaims_crashed_backend_row_with_fresh_heartbeat(self, db, monkeypatch):
        """AE1 / R1 — the crash window: a SIGKILLed gateway leaves a row whose heartbeat was
        fresh moments before the crash. The pid fence reclaims it on freshness-blind grounds:
        a dead owner is not liveness proof whatever the row says."""
        import subprocess

        server = self._server(db, monkeypatch)
        crashed = subprocess.Popen(["true"])
        crashed.wait()  # a real exited child: its pid is gone from the process table
        now = time.time()
        host = server._reaper_hostname()
        dead_id = f"default@{host}:{crashed.pid}:dead"
        self._plant(db, dead_id, pid=crashed.pid,
                    started_at=now - 300.0, last_heartbeat=now - 5.0, host=host)

        removed = server._reclaim_dead_backend_heartbeat_rows()

        assert removed == [dead_id]
        assert db.list_backend_heartbeats() == []

    @pytest.mark.platforms("posix")
    def test_reclaims_pid_reused_row_and_spares_owner_shaped_sibling(self, db, monkeypatch):
        """AE2 / R4 — pid reuse is DIRECTIONAL: a live child born hours after the row's
        ``started_at`` is a reuser (reclaim); the same live child with an owner-shaped
        ``started_at`` (at/after its birth, as the real refresher stamps) and a fresh heartbeat
        is the owner and is spared."""
        from hermes_cli.process_identity import _process_create_time

        import subprocess

        server = self._server(db, monkeypatch)
        child = subprocess.Popen(["sleep", "60"])
        try:
            create_time = _process_create_time(child.pid)
            assert create_time is not None, "test setup: psutil must see the child's birth"
            now = time.time()
            host = server._reaper_hostname()
            reused_id = f"default@{host}:{child.pid}:reused"
            live_id = f"default@{host}:{child.pid}:live"
            self._plant(db, reused_id, pid=child.pid,
                        started_at=create_time - 4 * 3600.0, last_heartbeat=now - 5.0, host=host)
            self._plant(db, live_id, pid=child.pid,
                        started_at=now, last_heartbeat=now - 5.0, host=host)

            removed = server._reclaim_dead_backend_heartbeat_rows()

            assert removed == [reused_id]
            assert [r["backend_id"] for r in db.list_backend_heartbeats()] == [live_id]
        finally:
            child.kill()
            child.wait()

    @pytest.mark.platforms("posix")
    def test_own_row_and_fresh_owner_shaped_sibling_are_untouched(self, db, monkeypatch):
        """R4 — the pass never deletes the caller's own row (even one planted with a dead pid:
        this process IS its owner) nor a healthy sibling's fresh owner-shaped row."""
        import subprocess

        server = self._server(db, monkeypatch)
        crashed = subprocess.Popen(["true"])
        crashed.wait()
        child = subprocess.Popen(["sleep", "60"])
        try:
            now = time.time()
            host = server._reaper_hostname()
            sibling_id = f"default@{host}:{child.pid}:live"
            self._plant(db, "reaper-self", pid=crashed.pid,
                        started_at=now - 300.0, last_heartbeat=now - 5.0, host=host)
            self._plant(db, sibling_id, pid=child.pid,
                        started_at=now, last_heartbeat=now - 5.0, host=host)

            removed = server._reclaim_dead_backend_heartbeat_rows()

            assert removed == []
            assert sorted(r["backend_id"] for r in db.list_backend_heartbeats()) == sorted([
                "reaper-self", sibling_id])
        finally:
            child.kill()
            child.wait()

    @pytest.mark.platforms("posix")
    def test_unknown_create_time_spares_fresh_row_but_stale_backstop_reclaims(self, db, monkeypatch):
        """R4 — without psutil the pass cannot disambiguate pid reuse, so a possibly-owned
        FRESH row is kept; the same-host staleness backstop still fires past the bound."""
        from hermes_cli import process_identity

        import subprocess

        server = self._server(db, monkeypatch)
        monkeypatch.setattr(process_identity, "_process_create_time", lambda pid: None)
        child = subprocess.Popen(["sleep", "60"])
        try:
            now = time.time()
            host = server._reaper_hostname()
            fresh_id = f"default@{host}:{child.pid}:fresh"
            stale_id = f"default@{host}:{child.pid}:stale"
            self._plant(db, fresh_id, pid=child.pid,
                        started_at=now, last_heartbeat=now - 5.0, host=host)
            self._plant(db, stale_id, pid=child.pid,
                        started_at=now - 500.0, last_heartbeat=now - 400.0, host=host)

            removed = server._reclaim_dead_backend_heartbeat_rows()

            assert removed == [stale_id]  # refresh pinned to 60 -> bound 180; 400s stale
            assert [r["backend_id"] for r in db.list_backend_heartbeats()] == [fresh_id]
        finally:
            child.kill()
            child.wait()

    @pytest.mark.platforms("posix")
    def test_live_owner_shaped_row_stale_past_same_host_bound_is_reclaimed(self, db, monkeypatch):
        """The observed incident (maestro observation 8d7dcac377abe7a03b9e6220): a LIVE pid in a
        slow shutdown — uncatchable by the pid fence, closed at SIGTERM receipt by Unit 4, and
        backstopped here for any handler-miss variant: stale past the same-host bound
        (max(3 × 60, 180) = 180s) means no longer liveness proof."""
        import subprocess

        server = self._server(db, monkeypatch)
        child = subprocess.Popen(["sleep", "60"])
        try:
            now = time.time()
            host = server._reaper_hostname()
            wedged_id = f"default@{host}:{child.pid}:wedged"
            self._plant(db, wedged_id, pid=child.pid,
                        started_at=now - 600.0, last_heartbeat=now - 400.0, host=host)

            assert server._reclaim_dead_backend_heartbeat_rows() == [wedged_id]
        finally:
            child.kill()
            child.wait()

    def test_foreign_host_rows_age_out_at_the_sweep_exemption_window(self, db, monkeypatch):
        """AE3 / R2 — foreign-host pids cannot be probed from here (a matching pid is a
        different process), so foreign rows only age out at 2 × session TTL — the sweep's own
        heartbeat-exemption window, past which deleting the row cannot change any sweep
        outcome; younger foreign rows are kept."""
        server = self._server(db, monkeypatch)
        monkeypatch.setattr(server, "_SESSION_TTL_S", 6 * 3600.0)  # pin: foreign TTL = 12h
        now = time.time()
        old_id = "default@other-box:31337:old"
        young_id = "default@other-box:31338:young"
        self._plant(db, old_id, pid=31337,
                    started_at=now - 14 * 3600.0, last_heartbeat=now - 13 * 3600.0, host="other-box")
        self._plant(db, young_id, pid=31338,
                    started_at=now - 2 * 3600.0, last_heartbeat=now - 3600.0, host="other-box")

        removed = server._reclaim_dead_backend_heartbeat_rows()

        assert removed == [old_id]
        assert [r["backend_id"] for r in db.list_backend_heartbeats()] == [young_id]

    def test_pass_is_a_noop_without_a_db(self, monkeypatch):
        from tui_gateway import server

        monkeypatch.setattr(server, "_get_db", lambda: None)

        assert server._reclaim_dead_backend_heartbeat_rows() == []


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

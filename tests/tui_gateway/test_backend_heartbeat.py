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
* Stale tombstone rows of backends that died without ``atexit`` are
  pruned at refresher start and on every refresh tick; fresh rows are
  never lost (A4 34ce45cd2093).
"""

from __future__ import annotations

import io
import logging
import time
import types

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


# ── stale tombstone prune (A4 34ce45cd2093) ─────────────────────────────
# A backend that dies without atexit (crash, kill -9, service restart) leaves a
# tombstone heartbeat row behind; the refresher reclaims tombstones older than
# the prune window while fresh rows always survive.


class TestStaleHeartbeatPrune:
    PRUNE_S = 900.0  # max(900, 15 × 60 s refresh) — the production default window

    def _arm_refresher(self, server, db, monkeypatch, *, refresh_s=0.0, prune_s=None):
        monkeypatch.setattr(server, "_get_db", lambda: db)
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", refresh_s)
        monkeypatch.setattr(
            server, "_HEARTBEAT_PRUNE_S", self.PRUNE_S if prune_s is None else prune_s, raising=False)
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)
        monkeypatch.setattr(server, "_backend_id_for_this_process", lambda: "test-backend-A")

    def test_start_prunes_predecessor_tombstone_keeps_fresh_rows(self, db, monkeypatch):
        """Refresher start reclaims a dead predecessor's row; a fresh sibling
        and this process's own row survive.  Register-once mode (refresh 0):
        the initial prune still runs and no loop/atexit is armed."""
        from tui_gateway import server

        registered = []
        monkeypatch.setattr(server, "atexit", types.SimpleNamespace(register=registered.append))
        self._arm_refresher(server, db, monkeypatch)  # refresh 0 → register-once
        now = time.time()
        db.register_backend_heartbeat(
            backend_id="predecessor-tombstone", pid=1, started_at=now - 26 * 3600,
            last_heartbeat=now - self.PRUNE_S - 60, profile="p", host="h")
        db.register_backend_heartbeat(
            backend_id="live-sibling", pid=2, started_at=now - 3600,
            last_heartbeat=now - 30, profile="p", host="h")

        server._start_backend_heartbeat_refresher()

        assert not registered  # register-once: loop never starts, no atexit clear
        ids = sorted(r["backend_id"] for r in db.list_backend_heartbeats())
        assert ids == ["live-sibling", "test-backend-A"]

    def test_loop_tick_prunes_row_that_ages_past_window(self, db, monkeypatch):
        """The refresh LOOP prunes on every tick, not only at start: a row
        created inside the window after start is reclaimed once it ages past
        it, while beating rows stay."""
        from tests.waiting import wait_until
        from tui_gateway import server

        registered = []
        monkeypatch.setattr(server, "atexit", types.SimpleNamespace(register=registered.append))
        self._arm_refresher(server, db, monkeypatch, refresh_s=0.05, prune_s=1.0)

        server._start_backend_heartbeat_refresher()
        assert len(registered) == 1  # loop mode armed the atexit clear

        now = time.time()
        db.register_backend_heartbeat(  # inside the 1 s window now, outside soon
            backend_id="ages-out", pid=1, started_at=now - 3600,
            last_heartbeat=now - 0.9, profile="p", host="h")
        db.register_backend_heartbeat(  # future-dated: beats every tick this test can run
            backend_id="beating-sibling", pid=2, started_at=now - 60,
            last_heartbeat=now + 5.0, profile="p", host="h")

        wait_until(
            lambda: "ages-out" not in [r["backend_id"] for r in db.list_backend_heartbeats()],
            timeout=10.0, what="tombstone aging past the prune window")

        ids = sorted(r["backend_id"] for r in db.list_backend_heartbeats())
        assert ids == ["beating-sibling", "test-backend-A"]  # own row kept fresh by the loop
        registered[0]()  # the atexit clear stops the loop thread

    def test_prune_failure_is_swallowed_and_registration_survives(self, db, monkeypatch, caplog):
        """A failing prune (locked db) logs at debug and never raises out of
        the refresher start; this process's own registration already landed."""
        from tui_gateway import server

        self._arm_refresher(server, db, monkeypatch)

        def _locked(*, max_age_seconds):
            raise RuntimeError("database is locked")

        monkeypatch.setattr(db, "prune_stale_heartbeats", _locked)
        with caplog.at_level(logging.DEBUG):
            server._start_backend_heartbeat_refresher()  # must not raise

        assert [r["backend_id"] for r in db.list_backend_heartbeats()] == ["test-backend-A"]
        assert any("prune failed" in rec.getMessage() for rec in caplog.records)

    def test_prune_noop_when_db_unavailable(self, monkeypatch):
        """DB unavailable (``_get_db`` → None): register and prune are both
        quiet no-ops."""
        from tui_gateway import server

        monkeypatch.setattr(server, "_get_db", lambda: None)
        monkeypatch.setattr(server, "_HEARTBEAT_REFRESH_S", 0.0)
        monkeypatch.setattr(server, "_HEARTBEAT_PRUNE_S", 900.0, raising=False)
        monkeypatch.setattr(server, "_heartbeat_refresher_started", False)

        server._start_backend_heartbeat_refresher()  # must not raise


class TestPruneWindowPolicy:
    """The prune window is 15 consecutive missed refresh beats, floored at
    15 minutes — dead beyond doubt while a live backend refreshes far inside."""

    def test_window_tracks_refresh_interval(self):
        from hermes_state_maintenance import backend_heartbeat_prune_max_age

        assert backend_heartbeat_prune_max_age(0.0) == 900.0    # register-once mode floor
        assert backend_heartbeat_prune_max_age(60.0) == 900.0   # 15 × 60 s = the floor
        assert backend_heartbeat_prune_max_age(120.0) == 1800.0
        assert backend_heartbeat_prune_max_age(-5.0) == 900.0   # malformed env never narrows


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

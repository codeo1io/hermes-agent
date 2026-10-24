"""Reclaim of gateway-heartbeat rows whose backend died without running ``atexit``.

Regression tests for finding 34ce45cd2093: a backend killed by SIGKILL, host outage or
user-manager exit never runs its ``atexit`` clear, and its per-nonce ``backend_id`` means a
respawned backend cannot re-inherit the dead predecessor's row — the row is permanent residue
that ages into every staleness threshold (maestro's ``phase1.session.operational`` counts such
rows as failures; three of them, chained by successive unclean exits, were observed live).
``prune_stale_heartbeats`` reclaims that residue with the turn-lease sweep's two-rule shape:

* Backstop — a row older than the window goes whatever its pid/host.
* Fast path — past the floor (two missed 60s refreshes) a row on THIS host whose pid is
  kernel-provably dead is reclaimed before it can age into any staleness threshold. Fresh
  rows, foreign-host rows and any pid probe doubt defer to the backstop: a stalled-but-alive
  backend must never lose its row early (and even a backstop deletion self-heals — the next
  refresh upserts the row back).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import psutil
import pytest

from hermes_state import SessionDB


# Mirror of hermes_state_gateway's module constants (pinned here as literals so a window change
# must consciously update this contract, not silently slide it).
WINDOW_S = 300.0  # _GATEWAY_HEARTBEAT_PRUNE_WINDOW_S: backstop, any pid/host
FLOOR_S = 120.0  # _GATEWAY_HEARTBEAT_DEAD_PID_FLOOR_S: fast path, dead LOCAL pid only


def _local_host() -> str:
    """What tui_gateway's ``_reaper_hostname()`` writes on this POSIX host."""
    return os.uname().nodename


def _reaped_pid() -> int:
    """A genuinely dead, already-reaped local PID (the turn-lease test fixture pattern)."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=30)
    assert not psutil.pid_exists(proc.pid), "reaped pid unexpectedly reused"
    return proc.pid


def _register(db: SessionDB, backend_id: str, *, pid: int, age_s: float, host: str) -> None:
    now = time.time()
    db.register_backend_heartbeat(
        backend_id=backend_id,
        pid=pid,
        started_at=now - age_s - 3600,
        last_heartbeat=now - age_s,
        profile="p",
        host=host,
    )


# ── backstop: past-window rows go whatever their pid/host ────────────────────


def test_backstop_drops_past_window_row_whatever_pid_and_host(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    _register(db, "ancient-remote", pid=1, age_s=WINDOW_S + 100, host="some-remote-host")
    _register(db, "fresh", pid=os.getpid(), age_s=5, host="h")

    assert db.prune_stale_heartbeats(max_age_seconds=WINDOW_S) == ["ancient-remote"]
    assert [r["backend_id"] for r in db.list_backend_heartbeats()] == ["fresh"]


def test_nonpositive_window_returns_empty_and_touches_nothing(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    _register(db, "stale", pid=1, age_s=WINDOW_S + 3600, host="h")

    assert db.prune_stale_heartbeats(max_age_seconds=0) == []
    assert db.prune_stale_heartbeats(max_age_seconds=-5) == []
    assert [r["backend_id"] for r in db.list_backend_heartbeats()] == ["stale"]


def test_prune_on_empty_store_is_empty_and_idempotent(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    assert db.prune_stale_heartbeats(max_age_seconds=WINDOW_S) == []
    assert db.prune_stale_heartbeats(max_age_seconds=WINDOW_S) == []


def test_second_prune_after_removal_is_empty(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    _register(db, "once", pid=1, age_s=WINDOW_S + 100, host="h")
    assert db.prune_stale_heartbeats(max_age_seconds=WINDOW_S) == ["once"]
    assert db.prune_stale_heartbeats(max_age_seconds=WINDOW_S) == []


# ── fast path: dead LOCAL pid past the floor ────────────────────────────────


@pytest.mark.platforms("posix")  # host matching is os.uname()-based
class TestDeadPidFastPath:
    def test_one_prune_retires_backstop_row_and_dead_local_pid_row(self, tmp_path):
        """The observed failure class: a backend uncleanly killed 200s ago (past the floor,
        within the window) leaves a row only the fast path can reclaim, in the same call that
        takes a past-window row."""
        dead = _reaped_pid()
        db = SessionDB(tmp_path / "state.db")
        _register(db, "past-window", pid=1, age_s=WINDOW_S + 100, host="some-remote-host")
        _register(db, "dead-local", pid=dead, age_s=(FLOOR_S + WINDOW_S) / 2, host=_local_host())

        assert sorted(db.prune_stale_heartbeats(max_age_seconds=WINDOW_S)) == [
            "dead-local", "past-window"]
        assert db.list_backend_heartbeats() == []

    def test_fresh_dead_pid_row_survives_the_floor(self, tmp_path):
        """Below the floor a dead backend's row keeps the orphan sweep's protection grace."""
        dead = _reaped_pid()
        db = SessionDB(tmp_path / "state.db")
        _register(db, "just-died", pid=dead, age_s=FLOOR_S / 4, host=_local_host())

        assert db.prune_stale_heartbeats(max_age_seconds=WINDOW_S) == []
        rows = db.list_backend_heartbeats()
        assert [r["backend_id"] for r in rows] == ["just-died"]
        assert rows[0]["pid"] == dead

    def test_alive_local_pid_row_within_window_survives(self, tmp_path):
        """A stalled-but-alive backend (this very process) must not lose its row early."""
        db = SessionDB(tmp_path / "state.db")
        _register(db, "starved-alive", pid=os.getpid(), age_s=(FLOOR_S + WINDOW_S) / 2,
                  host=_local_host())

        assert db.prune_stale_heartbeats(max_age_seconds=WINDOW_S) == []
        assert [r["backend_id"] for r in db.list_backend_heartbeats()] == ["starved-alive"]

    def test_foreign_host_dead_pid_row_survives_until_backstop(self, tmp_path):
        """Another host's pid is not locally checkable: kernel-proof doubt defers to the
        backstop, exactly like a foreign PID namespace in the lease sweep."""
        dead = _reaped_pid()
        db = SessionDB(tmp_path / "state.db")
        _register(db, "dead-remote", pid=dead, age_s=(FLOOR_S + WINDOW_S) / 2, host="remote-h")

        assert db.prune_stale_heartbeats(max_age_seconds=WINDOW_S) == []
        assert [r["backend_id"] for r in db.list_backend_heartbeats()] == ["dead-remote"]
        # …and the backstop still reclaims it once past the window.
        db._conn.execute("UPDATE gateway_heartbeats SET last_heartbeat = ?",
                         (time.time() - (WINDOW_S + 50),))
        db._conn.commit()
        assert db.prune_stale_heartbeats(max_age_seconds=WINDOW_S) == ["dead-remote"]

    def test_prune_touches_only_the_doomed_rows(self, tmp_path):
        """Conservation: survivors keep their row fields verbatim, not just their ids."""
        dead = _reaped_pid()
        db = SessionDB(tmp_path / "state.db")
        _register(db, "fresh-local", pid=os.getpid(), age_s=30, host=_local_host())
        _register(db, "starved-alive", pid=os.getpid(), age_s=200, host=_local_host())
        _register(db, "dead-local", pid=dead, age_s=200, host=_local_host())
        before = {r["backend_id"]: r for r in db.list_backend_heartbeats()}

        assert db.prune_stale_heartbeats(max_age_seconds=WINDOW_S) == ["dead-local"]
        after = {r["backend_id"]: r for r in db.list_backend_heartbeats()}
        assert set(after) == {"fresh-local", "starved-alive"}
        assert after == {k: before[k] for k in after}


# ── benign misprune safety: the refresh upsert recreates a row ──────────────


def test_pruned_backend_can_immediately_reregister(tmp_path):
    """Even a wrongly-deleted live row self-heals: the next refresh upserts it back, so the
    prune can never permanently strand a backend that is actually alive."""
    db = SessionDB(tmp_path / "state.db")
    _register(db, "mispruned", pid=os.getpid(), age_s=1, host="h")

    assert db.prune_stale_heartbeats(max_age_seconds=0.01) == ["mispruned"]
    _register(db, "mispruned", pid=os.getpid(), age_s=0, host="h")
    rows = db.list_backend_heartbeats()
    assert [r["backend_id"] for r in rows] == ["mispruned"]
    assert rows[0]["pid"] == os.getpid()

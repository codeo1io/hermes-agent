"""Stale session-turn-lease sweep + bounded background lease wait.

Live failure (2026-09-07): a lease held by pid 2522725 (dead since 08-31)
sat in ``session_turn_leases`` for 7 days because reclamation is lazy —
only the NEXT acquirer of that same conversation reclaims it, and that
conversation had no next acquirer. Concurrently, background wake turns
waited up to 1800s on the session lease behind a long foreground turn,
piling up waiter threads that each timed out and fired late synthetic
turns (the repeat-message / no-progress surface).
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time

import pytest

from hermes_state import SessionDB


def _insert_lease(db: SessionDB, conversation_id: str, holder: str,
                  expires_at: float) -> None:
    def _do(conn):
        conn.execute(
            "INSERT OR REPLACE INTO session_turn_leases "
            "(conversation_id, holder, acquired_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (conversation_id, holder, time.time(), expires_at),
        )

    db._execute_write(_do)


def _lease_count(db: SessionDB) -> int:
    row = db._conn.execute(
        "SELECT COUNT(*) FROM session_turn_leases"
    ).fetchone()
    return int(row[0])


def _lease_holders(db: SessionDB) -> list:
    rows = db._conn.execute(
        "SELECT conversation_id, holder FROM session_turn_leases"
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


class TestSweepSessionTurnLeases:
    def test_sweep_reaps_expired_lease(self, tmp_path):
        db = SessionDB(tmp_path / "state.db")
        db.create_session("conv-a", source="test")
        # Expired 60s ago.
        _insert_lease(db, "conv-a", "pid=999999:turn=old", time.time() - 60)
        assert _lease_count(db) == 1

        swept = db.sweep_session_turn_leases()
        assert swept == 1
        assert _lease_count(db) == 0

    def test_sweep_reaps_dead_holder_before_ttl(self, tmp_path):
        db = SessionDB(tmp_path / "state.db")
        db.create_session("conv-b", source="test")
        # Not expired (TTL far in the future) but the holder PID provably
        # does not exist. psutil.pid_exists(999999) is False on any host.
        _insert_lease(db, "conv-b", "pid=999999:turn=dead", time.time() + 3600)
        assert _lease_count(db) == 1

        swept = db.sweep_session_turn_leases()
        assert swept == 1
        assert _lease_count(db) == 0

    def test_sweep_keeps_live_holder_and_unexpired_lease(self, tmp_path):
        db = SessionDB(tmp_path / "state.db")
        db.create_session("conv-c", source="test")
        # This process is alive; the lease is fresh.
        _insert_lease(
            db, "conv-c", f"pid={os.getpid()}:turn=live", time.time() + 300
        )
        assert db.sweep_session_turn_leases() == 0
        assert _lease_count(db) == 1
        assert _lease_holders(db) == [("conv-c", f"pid={os.getpid()}:turn=live")]

    def test_sweep_reaps_only_doomed_rows_across_conversations(self, tmp_path):
        db = SessionDB(tmp_path / "state.db")
        db.create_session("live", source="test")
        db.create_session("dead", source="test")
        db.create_session("expired", source="test")
        _insert_lease(db, "live", f"pid={os.getpid()}:x", time.time() + 300)
        _insert_lease(db, "dead", "pid=999999:x", time.time() + 300)
        _insert_lease(db, "expired", "pid=999998:x", time.time() - 1)

        assert db.sweep_session_turn_leases() == 2
        assert _lease_holders(db) == [("live", f"pid={os.getpid()}:x")]

    def test_sweep_is_idempotent_and_safe_on_empty_table(self, tmp_path):
        db = SessionDB(tmp_path / "state.db")
        assert db.sweep_session_turn_leases() == 0
        db.create_session("conv", source="test")
        _insert_lease(db, "conv", "pid=999999:x", time.time() - 1)
        assert db.sweep_session_turn_leases() == 1
        assert db.sweep_session_turn_leases() == 0


class TestBoundedBackgroundLeaseWait:
    """acquire_session_turn_lease honors small wait_seconds budgets."""

    def test_bounded_wait_fails_fast_when_held(self, tmp_path):
        db = SessionDB(tmp_path / "state.db")
        db.create_session("conv", source="test")
        holder = f"pid={os.getpid()}:turn=foreground"
        assert db.try_acquire_session_turn_lease("conv", holder, ttl_seconds=60)

        started = time.monotonic()
        background = f"pid={os.getpid()}:turn=background"
        got = db.acquire_session_turn_lease(
            "conv", background,
            ttl_seconds=60,
            wait_seconds=0.2,
            poll_interval_seconds=0.02,
        )
        elapsed = time.monotonic() - started

        assert got is False
        assert elapsed < 2.0, f"bounded wait took {elapsed:.1f}s"
        db.release_session_turn_lease("conv", holder)

    def test_bounded_wait_succeeds_after_release(self, tmp_path):
        db = SessionDB(tmp_path / "state.db")
        db.create_session("conv", source="test")
        holder = f"pid={os.getpid()}:turn=fg"
        assert db.try_acquire_session_turn_lease("conv", holder, ttl_seconds=60)

        def release():
            time.sleep(0.1)
            db.release_session_turn_lease("conv", holder)

        t = threading.Thread(target=release)
        t.start()
        try:
            bg = f"pid={os.getpid()}:turn=bg"
            assert db.acquire_session_turn_lease(
                "conv", bg, ttl_seconds=60,
                wait_seconds=5.0, poll_interval_seconds=0.02,
            )
            db.release_session_turn_lease("conv", bg)
        finally:
            t.join(timeout=2)

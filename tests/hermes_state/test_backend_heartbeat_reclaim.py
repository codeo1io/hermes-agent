"""Storage layer of the heartbeat reclaim pass (dead-backend gateway heartbeat rows).

``SessionDB.drop_backend_heartbeats`` is the race-guarded bulk delete the gateway heartbeat
refresher's reclaim pass uses to remove dead owners' ``gateway_heartbeats`` rows (maestro A4,
finding 34ce45cd2093: a stale row outliving its crashed/slowly-shutting-down gateway fails
contract ``phase1.session.operational``). The guard is the contract under test: a row is
deletable only while its ``last_heartbeat`` has not advanced past the snapshot the caller
observed — a live owner that refreshed between the reclaim pass's list and its delete must be
spared, whatever the fence decided a moment earlier (belt: the owner re-upserts on its next
refresh anyway; braces: it never even disappears).
"""

from __future__ import annotations

import pytest

from hermes_state import SessionDB


@pytest.fixture
def db(tmp_path):
    return SessionDB(tmp_path / "state.db")


def _plant(db: SessionDB, backend_id: str, *, pid: int = 4242, last_heartbeat: float) -> None:
    db.register_backend_heartbeat(
        backend_id=backend_id, pid=pid, started_at=last_heartbeat,
        last_heartbeat=last_heartbeat, profile="default", host="test-host")


class TestDropBackendHeartbeats:
    def test_deletes_stale_snapshot_rows_and_returns_ids(self, db):
        _plant(db, "default@test-host:111:aaaa", last_heartbeat=100.0)
        _plant(db, "default@test-host:222:bbbb", last_heartbeat=100.0)

        removed = db.drop_backend_heartbeats(
            {"default@test-host:111:aaaa": 100.0, "default@test-host:222:bbbb": 100.0})

        assert sorted(removed) == ["default@test-host:111:aaaa", "default@test-host:222:bbbb"]
        assert db.list_backend_heartbeats() == []

    def test_race_guard_spares_row_that_refreshed_past_snapshot(self, db):
        # The reclaim pass listed the row at t=100; the owner refreshed at t=160 before the
        # delete landed. The row must survive — its moved timestamp is proof of a live owner.
        _plant(db, "default@test-host:111:aaaa", last_heartbeat=160.0)

        removed = db.drop_backend_heartbeats({"default@test-host:111:aaaa": 100.0})

        assert removed == []
        rows = db.list_backend_heartbeats()
        assert [r["backend_id"] for r in rows] == ["default@test-host:111:aaaa"]

    def test_boundary_equal_timestamp_is_deletable(self, db):
        # `<=`, not `<`: the snapshot saw exactly this heartbeat, so the owner has not
        # refreshed since the reclaim pass looked.
        _plant(db, "default@test-host:111:aaaa", last_heartbeat=100.0)

        assert db.drop_backend_heartbeats({"default@test-host:111:aaaa": 100.0}) == [
            "default@test-host:111:aaaa"]

    def test_empty_and_unknown_ids_are_noops(self, db):
        assert db.drop_backend_heartbeats({}) == []

        _plant(db, "default@test-host:111:aaaa", last_heartbeat=100.0)
        assert db.drop_backend_heartbeats({"default@test-host:999:zzzz": 100.0}) == []
        assert len(db.list_backend_heartbeats()) == 1

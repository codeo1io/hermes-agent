"""Contract of the heartbeat reclaim pass's storage verbs (dead-backend gateway heartbeat rows).

``maintenance.list_backend_heartbeats`` enumerates the ``gateway_heartbeats`` table for the
reaper's dead-owner reclaim pass, and ``maintenance.drop_backend_heartbeats`` is its
race-guarded bulk delete (maestro A4, finding 34ce45cd2093: a stale row outliving its
crashed/slowly-shutting-down gateway fails contract ``phase1.session.operational``). The guard
is the contract under test: a row is deletable only while its ``last_heartbeat`` has not
advanced past the snapshot the caller observed — a live owner that refreshed between the
reclaim pass's list and its delete must be spared, whatever the fence decided a moment
earlier (belt: the owner re-upserts on its next refresh anyway; braces: it never even
disappears).
"""

from __future__ import annotations

NOW = 1767225600.0


def _plant(store, backend_id, *, pid: int = 4242, last_heartbeat: float) -> None:
    store.maintenance.register_backend_heartbeat(
        backend_id=backend_id, pid=pid, started_at=last_heartbeat,
        last_heartbeat=last_heartbeat, profile="default", host="test-host")


def test_drop_deletes_snapshot_stale_rows_in_input_order_and_lists_survivors(backend, scope_a):
    store_a = backend.open(scope_a)
    _plant(store_a, "default@test-host:222:bbbb", last_heartbeat=100.0)
    _plant(store_a, "default@test-host:111:aaaa", last_heartbeat=100.0)
    _plant(store_a, "default@test-host:333:cccc", last_heartbeat=100.0)

    removed = store_a.maintenance.drop_backend_heartbeats({
        "default@test-host:333:cccc": 100.0, "default@test-host:111:aaaa": 100.0})

    # Input order, not table order; the unlisted row survives and lists deterministically.
    assert removed == ["default@test-host:333:cccc", "default@test-host:111:aaaa"]
    rows = store_a.maintenance.list_backend_heartbeats()
    assert [row["backend_id"] for row in rows] == ["default@test-host:222:bbbb"]
    assert rows[0]["pid"] == 4242 and rows[0]["host"] == "test-host"


def test_race_guard_spares_row_refreshed_past_snapshot(backend, scope_a):
    # The reclaim pass listed the row at t=100; the owner refreshed at t=160 before the delete
    # landed. The row must survive — its moved timestamp is proof of a live owner.
    store_a = backend.open(scope_a)
    _plant(store_a, "default@test-host:111:aaaa", last_heartbeat=160.0)

    assert store_a.maintenance.drop_backend_heartbeats(
        {"default@test-host:111:aaaa": 100.0}) == []
    rows = store_a.maintenance.list_backend_heartbeats()
    assert [row["backend_id"] for row in rows] == ["default@test-host:111:aaaa"]
    assert rows[0]["last_heartbeat"] == 160.0


def test_boundary_equal_timestamp_is_deletable(backend, scope_a):
    # `<=`, not `<`: the snapshot saw exactly this heartbeat, so the owner has not refreshed
    # since the reclaim pass looked.
    store_a = backend.open(scope_a)
    _plant(store_a, "default@test-host:111:aaaa", last_heartbeat=100.0)

    assert store_a.maintenance.drop_backend_heartbeats(
        {"default@test-host:111:aaaa": 100.0}) == ["default@test-host:111:aaaa"]


def test_empty_and_unknown_ids_are_noops(backend, scope_a):
    store_a = backend.open(scope_a)
    assert store_a.maintenance.drop_backend_heartbeats({}) == []

    _plant(store_a, "default@test-host:111:aaaa", last_heartbeat=100.0)
    assert store_a.maintenance.drop_backend_heartbeats(
        {"default@test-host:999:zzzz": 100.0}) == []
    rows = store_a.maintenance.list_backend_heartbeats()
    assert [row["backend_id"] for row in rows] == ["default@test-host:111:aaaa"]

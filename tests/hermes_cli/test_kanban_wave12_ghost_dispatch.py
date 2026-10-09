"""Wave-12 ghost dispatch + guard-parity regression (2026-09-24, fix-queue 97).

Shape (evidence t_0f4cedb9 / t_ebcf6b4c, forensics on t_128906f4): a lane
creates rows and deletes them within ~3 minutes (hand-merge cleanup, a
crashing creator, rows deleted on landing). The 5-minute sentinel tick never
intersected that churn, but the DISPATCHER had no minimum-age gate, so its
next tick claimed the still-live ghost rows and spawned real workers — which
then honestly refused ("task not found") after burning spawn slots, and the
lane's hard delete orphaned the run rows.

Two pinned behaviors:

1. ``_lane_rows`` hides rows younger than ``_DISPATCH_MIN_AGE_SECONDS`` —
   transient create→delete churn ages out before it is ever claimable, while
   an old-enough row still dispatches on the very same call (no added delay
   for the backlog).
2. ``connect()`` runs the test-isolation choke — the wave-12 leak lane ran a
   scratch checkout whose ``connect`` was missing ``_ensure_test_isolation``
   (only ``init_db`` had it); parity means ANY checkout, deployed or scratch,
   refuses the production board from a test context on the connect path too.
"""

from __future__ import annotations

import gc

import sqlite3
import time
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as kbd

pytestmark = pytest.mark.dispatch_min_age_real


def _seed_row(conn: sqlite3.Connection, tid: str, *, created_at: int, status: str = "ready") -> None:
    conn.execute(
        "INSERT INTO tasks (id, title, assignee, status, priority, created_by, created_at)"
        " VALUES (?, ?, 'default', ?, 0, NULL, ?)",
        (tid, tid, status, created_at),
    )
    conn.commit()


@pytest.fixture
def board(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "kanban.db"
    kb.init_db(db)
    return kbc.connect(db)


def test_lane_rows_hides_rows_younger_than_min_age(board):
    now = int(time.time())
    _seed_row(board, "t_ghost_young", created_at=now)  # live for <1s so far
    _seed_row(board, "t_ghost_edge", created_at=now - kbd._DISPATCH_MIN_AGE_SECONDS + 10)
    _seed_row(board, "t_settled", created_at=now - kbd._DISPATCH_MIN_AGE_SECONDS - 1)
    ids = {row["id"] for row in kbd._lane_rows(board, "ready")}
    assert "t_settled" in ids, "a row past the min age must remain dispatchable"
    assert "t_ghost_young" not in ids, (
        "ghost-dispatch recurrence: a row younger than one tick is claimable"
    )
    assert "t_ghost_edge" not in ids, (
        "the gate boundary is inclusive-settle: row must reach the full min age"
    )


def test_lane_rows_min_age_not_configurable_to_zero_by_accident(board):
    # The constant is the contract; pin it against quiet-creep edits.
    assert kbd._DISPATCH_MIN_AGE_SECONDS >= 300, "min age below one sentinel tick reopens wave-12"


def test_dispatch_tick_spawns_nothing_for_young_transient_rows(board, monkeypatch):
    now = int(time.time())
    _seed_row(board, "t_wave12_ghost", created_at=now)
    spawned = []
    monkeypatch.setattr(kbd, "_dispatch_lane_task", lambda *a, **k: spawned.append(a) or (True, None))
    result = kbd.dispatch_once(board, spawn_fn=lambda *a, **k: 12345)
    assert spawned == [], "dispatch_tick spawned for a row younger than the min-age gate"
    assert result.spawned == [], "dispatch_once spawned for a row younger than the min-age gate"


def test_connect_runs_the_test_isolation_choke(monkeypatch, tmp_path):
    """connect() must refuse a production-root kanban path from a test context.

    Wave-9's guard was init_db-only; the wave-12 scratch checkout proved the
    connect path is the one real leak lanes take. Behavioral: point the
    production-root resolver at a temp "real board" (the guard late-imports the
    resolver from hermes_state_guard, so the module attribute is the seam) and
    assert the UNWRAPPED connect refuses it before any write. The conftest
    write-guard wraps ``connect`` per-test, so recover the module-level
    original it captured (its first closure cell) and drive THAT.
    """
    func = kbc.connect
    if func.__code__.co_name != "connect":
        func = next(
            (c.cell_contents for c in func.__closure__ or () if callable(c.cell_contents)),
            func,
        )
    import hermes_state_guard as _hsg

    root = tmp_path / "prod-root"
    root.mkdir()
    board = root / "kanban.db"
    board.write_bytes(b"live-board")
    monkeypatch.setattr(_hsg, "_real_platform_state_root", lambda: root)
    before = board.stat().st_mtime_ns
    with pytest.raises(RuntimeError, match="test-isolation guard|kanban_write_guard"):
        func(board)
    assert board.stat().st_mtime_ns == before

"""Dispatch min-age gate knob: config-driven, default preserved (rm-058).

Wave-12 (#131747) added a create-then-delete churn gate: rows younger than a
minimum age are invisible to the gateway dispatcher. The gate shipped with a
hardcoded 300 s default and an env-only override, while user-facing help still
promised next-tick pickup. rm-058 reconciles the three:

* ``kanban.dispatch_min_age_seconds`` in config.yaml is the sanctioned knob
  (0 disables the gate for boards whose rows are stable on insert);
* ``HERMES_KANBAN_DISPATCH_MIN_AGE`` remains the env override (env wins) for
  tests and diagnostics;
* the default stays one sentinel tick (300 s) — wave-12's churn ceiling.

These tests pin the resolution order and the SQL gate boundary. They opt out
of the suite-wide env mask via ``dispatch_min_age_real`` and inject real
config.yaml files into the isolated HERMES_HOME (real resolution chain).
"""
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path

import pytest

import hermes_cli.kanban_db_dispatch as kbd
from hermes_cli import kanban_db_tasks
from hermes_cli.kanban_db import core as kanban_db

pytestmark = [pytest.mark.dispatch_min_age_real]


def _write_kanban_config(value: float) -> None:
    """Write a real config.yaml (kanban.dispatch_min_age_seconds) into the
    test-isolated HERMES_HOME so the knob is read through the production
    load_config() path, not a monkeypatch."""
    home = Path(os.environ["HERMES_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        f"kanban:\n  dispatch_min_age_seconds: {value}\n", encoding="utf-8"
    )


def _ensure_no_config() -> None:
    home = Path(os.environ["HERMES_HOME"])
    cfg = home / "config.yaml"
    if cfg.exists():
        cfg.unlink()


@pytest.fixture(autouse=True)
def _clean_min_age_env(monkeypatch):
    monkeypatch.delenv("HERMES_KANBAN_DISPATCH_MIN_AGE", raising=False)
    _ensure_no_config()
    yield


@contextmanager
def _open_db(db_path):
    with closing(sqlite3.connect(db_path)) as conn:
        kanban_db.init_schema(conn)
        kanban_db.lanes.ensure_lane(conn, "alpha", 1)
        yield conn


def _row_ids(conn, status: str = "ready") -> set:
    return {row[0] for row in kbd._lane_rows(conn, status=status)}


# --------------------------------------------------------------------------
# Resolution order: env > config > sentinel default
# --------------------------------------------------------------------------


def test_resolution_default_is_one_sentinel_tick():
    assert kbd._dispatch_min_age_seconds() == 300.0


def test_resolution_env_still_overrides(monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_DISPATCH_MIN_AGE", "0")
    assert kbd._dispatch_min_age_seconds() == 0.0
    monkeypatch.setenv("HERMES_KANBAN_DISPATCH_MIN_AGE", "7")
    assert kbd._dispatch_min_age_seconds() == 7.0


def test_resolution_config_knob_honored():
    _write_kanban_config(0)
    assert kbd._dispatch_min_age_seconds() == 0.0
    _write_kanban_config(5)
    assert kbd._dispatch_min_age_seconds() == 5.0


def test_resolution_env_beats_config(monkeypatch):
    _write_kanban_config(300)
    monkeypatch.setenv("HERMES_KANBAN_DISPATCH_MIN_AGE", "0")
    assert kbd._dispatch_min_age_seconds() == 0.0


# --------------------------------------------------------------------------
# SQL gate boundary follows the knob (fresh task claimable within one tick
# of creation when the operator opts out of the churn gate)
# --------------------------------------------------------------------------


def test_lane_rows_honors_config_knob_zero(tmp_path):
    _write_kanban_config(0)
    now = int(time.time())
    with _open_db(tmp_path / "board.db") as conn:
        kanban_db_tasks.add_task(
            conn, "alpha", "t_fresh", created_at=now, status="ready"
        )
        kanban_db_tasks.add_task(
            conn, "alpha", "t_backlog", created_at=now - 1200, status="ready"
        )
        ids = _row_ids(conn)
    assert "t_fresh" in ids
    assert "t_backlog" in ids


def test_lane_rows_honors_config_knob_boundary(tmp_path):
    _write_kanban_config(5)
    now = int(time.time())
    with _open_db(tmp_path / "board.db") as conn:
        kanban_db_tasks.add_task(
            conn, "alpha", "t_ten_s", created_at=now - 10, status="ready"
        )
        kanban_db_tasks.add_task(
            conn, "alpha", "t_two_s", created_at=now - 2, status="ready"
        )
        ids = _row_ids(conn)
    assert "t_ten_s" in ids
    assert "t_two_s" not in ids


def test_lane_rows_default_still_gates_young_rows(tmp_path):
    """Feature preservation: with no env and no config override the gate
    keeps wave-12's churn window (young rows hidden, backlog visible)."""
    now = int(time.time())
    with _open_db(tmp_path / "board.db") as conn:
        kanban_db_tasks.add_task(
            conn, "alpha", "t_young_70", created_at=now - 70, status="ready"
        )
        kanban_db_tasks.add_task(
            conn, "alpha", "t_old_310", created_at=now - 310, status="ready"
        )
        ids = _row_ids(conn)
    assert "t_young_70" not in ids
    assert "t_old_310" in ids

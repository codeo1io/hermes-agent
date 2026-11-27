"""Memory-aware kanban dispatch guard (OOF-30 / OOF-77).

Two production incidents shared the same failure shape: no
``kanban.max_in_progress`` configured, a busy board, and a small hosted VM —
the dispatcher fanned out 26-31 concurrent workers, the host swap-thrashed,
and the whole machine (dashboard included) became unreachable.

Covers the two safeguards added in response:

1. :func:`hermes_cli.kanban_db_dispatch.derive_default_max_in_progress` /
   :func:`hermes_cli.kanban_db_dispatch.resolve_max_in_progress` — memory-derived
   default global concurrency cap when the operator never set one.
2. The live memory-pressure guard inside ``dispatch_once`` — critical
   pressure spawns nothing; elevated pressure spawns at most one; unknown
   imposes no restriction (fail-open).
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_dispatch as kbd
from hermes_cli import kanban_db_connect as kbc


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    """Isolated HERMES_HOME with an empty kanban DB."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


GIB = 1024 * 1024  # KiB per GiB


# ---------------------------------------------------------------------------
# derive_default_max_in_progress / resolve_max_in_progress
# ---------------------------------------------------------------------------


def test_derived_cap_small_vm_floors_at_two():
    # 1 GiB VM (the incident shape): 1024 // 512 = 2 workers.
    assert kbd.derive_default_max_in_progress({"mem_total_kib": 1 * GIB}) == 2
    # Even tiny VMs keep a floor of 2 so boards still make progress.
    assert kbd.derive_default_max_in_progress({"mem_total_kib": GIB // 4}) == 2




def test_derived_cap_fails_open_without_memtotal():
    assert kbd.derive_default_max_in_progress({}) is None
    assert kbd.derive_default_max_in_progress({"mem_total_kib": 0}) is None
    assert kbd.derive_default_max_in_progress({"mem_total_kib": -5}) is None
    assert kbd.derive_default_max_in_progress({"mem_total_kib": True}) is None
    assert kbd.derive_default_max_in_progress({"mem_total_kib": "1048576"}) is None


def test_resolve_max_in_progress_explicit_config_wins(monkeypatch):
    monkeypatch.setattr(
        kbd, "_system_memory_sample", lambda: {"mem_total_kib": 1 * GIB}
    )
    # Operator said 6 on a 1 GiB box — their call, even above the derived 2.
    assert kbd.resolve_max_in_progress(6) == 6
    assert kbd.resolve_max_in_progress(1) == 1


def test_resolve_max_in_progress_derives_when_unset(monkeypatch):
    monkeypatch.setattr(
        kbd, "_system_memory_sample", lambda: {"mem_total_kib": 1 * GIB}
    )
    assert kbd.resolve_max_in_progress(None) == 2


def test_resolve_max_in_progress_unset_and_unknown_memory_is_uncapped(monkeypatch):
    monkeypatch.setattr(kbd, "_system_memory_sample", dict)
    assert kbd.resolve_max_in_progress(None) is None


# ---------------------------------------------------------------------------
# _memory_pressure_level
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("full_psi", "expected"),
    [(0.0, "ok"), (4.99, "ok"), (5.0, "elevated"),
     (9.99, "elevated"), (10.0, "critical"), (70.0, "critical"),
     (-1.0, "ok"), (101.0, "ok"), (float("nan"), "ok"), (True, "ok")],
)
def test_full_stall_psi_overrides_healthy_memavailable(full_psi, expected):
    sample = {
        "mem_total_kib": GIB,
        "mem_available_kib": GIB // 2,
        "memory_full_psi_avg60": full_psi,
    }
    assert kbd._memory_pressure_level(sample) == expected


def test_critical_memavailable_stays_critical_with_moderate_psi():
    sample = {
        "mem_total_kib": GIB,
        "mem_available_kib": 32 * 1024,
        "memory_full_psi_avg60": 5.5,
    }
    assert kbd._memory_pressure_level(sample) == "critical"


@pytest.mark.real_memory_guard
def test_memory_sample_includes_full_stall_psi(monkeypatch):
    from gateway import lifecycle_ledger

    monkeypatch.setattr(
        lifecycle_ledger, "sample_memory",
        lambda: {"mem_total_kib": GIB, "mem_available_kib": GIB // 2},
    )
    monkeypatch.setattr(kbd, "_psi_full_avg60", lambda: 27.5)
    sample = kbd._system_memory_sample()
    assert sample["memory_full_psi_avg60"] == 27.5
    assert kbd._memory_pressure_level(sample) == "critical"


def test_psi_reader_extracts_full_avg60_not_some(monkeypatch):
    data = "some avg10=99.0 avg60=95.0 avg300=80.0 total=1\nfull avg10=12.0 avg60=10.5 avg300=8.0 total=2\n"
    monkeypatch.setattr(kbd, "open", lambda *a, **kw: StringIO(data), raising=False)
    assert kbd._psi_full_avg60() == 10.5


def test_psi_reader_missing_or_malformed_falls_back(monkeypatch):
    for data in ("some avg60=99.0\n", "full avg60=nan\n", "full avg60=garbage\n"):
        monkeypatch.setattr(kbd, "open", lambda *a, **kw: StringIO(data), raising=False)
        assert kbd._psi_full_avg60() is None






# ---------------------------------------------------------------------------
# dispatch_once under pressure
# ---------------------------------------------------------------------------


def _pressure_sample(level: str) -> dict:
    total = 1 * GIB
    if level == "critical":
        return {"mem_available_kib": 32 * 1024, "mem_total_kib": total}
    if level == "elevated":
        return {"mem_available_kib": 100 * 1024, "mem_total_kib": total}
    return {"mem_available_kib": total // 2, "mem_total_kib": total}


@pytest.mark.parametrize(
    "sample",
    [
        _pressure_sample("critical"),
        {**_pressure_sample("ok"), "memory_full_psi_avg60": 70.0},
    ],
)
def test_dispatch_spawns_nothing_under_critical_pressure(
    kanban_home, all_assignees_spawnable, monkeypatch, sample,
):
    monkeypatch.setattr(kbd, "_system_memory_sample", lambda: sample)
    spawns = []

    def fake_spawn(task, workspace, board=None):
        spawns.append(task.id)
        return 42

    with kbc.connect() as conn:
        for title in ("a", "b", "c"):
            kb.create_task(conn, title=title, assignee="alice")
        res = kbd.dispatch_once(conn, spawn_fn=fake_spawn)

    assert not spawns
    assert not res.spawned
    assert res.memory_pressure == "critical"


def test_dispatch_critical_pressure_defers_not_drops(
    kanban_home, all_assignees_spawnable, monkeypatch,
):
    """Tasks skipped under pressure stay 'ready' and spawn once memory clears."""
    sample = {"value": _pressure_sample("critical")}
    monkeypatch.setattr(kbd, "_system_memory_sample", lambda: sample["value"])
    spawns = []

    def fake_spawn(task, workspace, board=None):
        spawns.append(task.id)
        return 42

    with kbc.connect() as conn:
        task = kb.create_task(conn, title="a", assignee="alice")
        kbd.dispatch_once(conn, spawn_fn=fake_spawn)
        assert not spawns
        row = kb.get_task(conn, task)
        assert row is not None and row.status == "ready"

        sample["value"] = _pressure_sample("ok")
        res = kbd.dispatch_once(conn, spawn_fn=fake_spawn)

    assert spawns == [task]
    assert res.memory_pressure is None


def test_dispatch_elevated_pressure_spawns_at_most_one(
    kanban_home, all_assignees_spawnable, monkeypatch,
):
    monkeypatch.setattr(
        kbd, "_system_memory_sample", lambda: _pressure_sample("elevated")
    )
    spawns = []

    def fake_spawn(task, workspace, board=None):
        spawns.append(task.id)
        return 42

    with kbc.connect() as conn:
        for title in ("a", "b", "c"):
            kb.create_task(conn, title=title, assignee="alice")
        res = kbd.dispatch_once(conn, spawn_fn=fake_spawn)

    assert len(spawns) == 1
    assert res.memory_pressure == "elevated"


def test_dispatch_elevated_pressure_does_not_widen_tighter_budget(
    kanban_home, all_assignees_spawnable, monkeypatch,
):
    """A caller cap already at 0 remaining must not be widened to 1."""
    monkeypatch.setattr(
        kbd, "_system_memory_sample", lambda: _pressure_sample("elevated")
    )
    spawns = []

    def fake_spawn(task, workspace, board=None):
        spawns.append(task.id)
        return 42

    with kbc.connect() as conn:
        running = kb.create_task(conn, title="running", assignee="alice")
        kb.claim_task(conn, running)
        kb.create_task(conn, title="ready", assignee="bob")
        res = kbd.dispatch_once(conn, spawn_fn=fake_spawn, max_in_progress=1)

    assert not spawns
    assert not res.spawned


def test_dispatch_unknown_pressure_imposes_no_restriction(
    kanban_home, all_assignees_spawnable, monkeypatch,
):
    monkeypatch.setattr(kbd, "_system_memory_sample", dict)
    spawns = []

    def fake_spawn(task, workspace, board=None):
        spawns.append(task.id)
        return 42

    with kbc.connect() as conn:
        for title in ("a", "b", "c"):
            kb.create_task(conn, title=title, assignee="alice")
        res = kbd.dispatch_once(conn, spawn_fn=fake_spawn)

    assert len(spawns) == 3
    assert res.memory_pressure is None


def test_dispatch_critical_pressure_still_runs_reclaim_bookkeeping(
    kanban_home, all_assignees_spawnable, monkeypatch,
):
    """The guard must only stop NEW spawns — reclaim/promotion still run."""
    monkeypatch.setattr(
        kbd, "_system_memory_sample", lambda: _pressure_sample("critical")
    )
    with kbc.connect() as conn:
        parent = kb.create_task(conn, title="parent", assignee="alice")
        child = kb.create_task(
            conn, title="child", assignee="alice", parents=[parent],
        )
        conn.execute("UPDATE tasks SET status = 'done' WHERE id = ?", (parent,))
        res = kbd.dispatch_once(conn, spawn_fn=lambda *a, **k: 42)
        row = kb.get_task(conn, child)

    # Promotion (todo -> ready once parents are done) happened despite the
    # spawn freeze.
    assert res.memory_pressure == "critical"
    assert row is not None
    assert row.status == "ready"

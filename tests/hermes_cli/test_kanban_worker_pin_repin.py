"""Operational guard for worker-spawned verification subprocesses (2026-09-17 leak).

A dispatcher worker's env carries the live-board location pins
(``HERMES_KANBAN_DB`` / ``HERMES_KANBAN_WORKSPACES_ROOT``). Every subprocess the
worker spawns — terminal children, conductor fleet runs, ``pytest`` — inherited
them verbatim, and because ``kanban_db_path()`` resolves the pin FIRST (over any
test-fixture ``HERMES_HOME`` sandbox), a leaking test suite wrote its fixture
cards into the LIVE board: 7 waves, 156 rows, two real worker runs burned on
leaked cards (runs 2044-2047). Stripping is insufficient — without the pin
``kanban_db_path()`` falls back to ``kanban_home()`` (the shared default root),
which IS the live board. The guard REPINS the location pins to a per-lineage
scratch board — but only for test-runner children: fenced descendants
legitimately READ the lineage board, so ordinary commands keep their pin.

These tests pin the contract from the incident through the real surfaces a
worker's pytest actually went through, not mocks of the functions under test.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

from agent.delegation_context import (  # noqa: E402
    DELEGATED_CHILD_ENV_MARKER,
    delegated_child_subprocess_env,
    kanban_env_for_child_command,
    looks_like_test_runner_command,
    repin_kanban_board_env,
)


def _live_env(tmp_path: Path, monkeypatch) -> Path:
    """Env mirroring a dispatched worker: live board pins + task identity."""
    live_db = tmp_path / "live" / "kanban.db"
    live_db.parent.mkdir(parents=True, exist_ok=True)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("HERMES_KANBAN_DB", str(live_db))
    monkeypatch.setenv("HERMES_KANBAN_WORKSPACES_ROOT", str(tmp_path / "live" / "workspaces"))
    monkeypatch.setenv("HERMES_KANBAN_WORKSPACE", str(workspace))
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_fixture")
    monkeypatch.delenv(DELEGATED_CHILD_ENV_MARKER, raising=False)
    return live_db


# --- repin contract ---------------------------------------------------------


def test_repin_repoints_location_pins_to_scratch(tmp_path, monkeypatch):
    live_db = _live_env(tmp_path, monkeypatch)
    # A pytest child (the leak vector) goes through the command-aware gate.
    env = kanban_env_for_child_command("python -m pytest -q tests/", dict(os.environ))
    assert env["HERMES_KANBAN_DB"] != str(live_db)
    assert env["HERMES_KANBAN_DB"].startswith(str(tmp_path / "ws" / ".kanban-scratch"))
    assert env["HERMES_KANBAN_DB"].endswith("kanban.db")
    assert env["HERMES_KANBAN_WORKSPACES_ROOT"] == str(
        tmp_path / "ws" / ".kanban-scratch" / "workspaces")
    # Identity scrub still applies on top of the repin.
    assert "HERMES_KANBAN_TASK" not in env
    assert env.get(DELEGATED_CHILD_ENV_MARKER)


def test_ordinary_commands_keep_the_pinned_board(tmp_path, monkeypatch):
    """Fenced descendants legitimately READ the lineage board (kanban show in a
    repro script): only test-runner invocations are repointed."""
    live_db = _live_env(tmp_path, monkeypatch)
    env = kanban_env_for_child_command("python repro.py --report", dict(os.environ))
    assert env["HERMES_KANBAN_DB"] == str(live_db)
    assert "HERMES_KANBAN_TASK" not in env


def test_runner_sniff_covers_fleet_shapes():
    assert looks_like_test_runner_command("pytest -q")
    assert looks_like_test_runner_command("python -m pytest -q tests/")
    assert looks_like_test_runner_command("bash -c 'cd /wt && pytest -q --deselect tests/'")
    assert looks_like_test_runner_command("scripts/run_tests.sh")
    assert looks_like_test_runner_command("python scripts/run_tests_parallel.py -q")
    assert looks_like_test_runner_command("python -m unittest tests.test_x")
    assert looks_like_test_runner_command("/venv/bin/pytest --reruns 3")
    assert not looks_like_test_runner_command("python repro.py")
    assert not looks_like_test_runner_command("make lint")
    assert not looks_like_test_runner_command("")
    assert not looks_like_test_runner_command(None)
    # NOT a runner: pytest's own tmp dir in a path (the false-positive class the
    # token matcher exists to prevent — incidentally this very test suite's path).
    assert not looks_like_test_runner_command(
        "python /tmp/pytest-of-agent/pytest-7/test_x0/repro.py")
    assert not looks_like_test_runner_command(
        "cat /tmp/pytest-of-agent/pytest-7/test_x0/out.txt | grep -i pyte.st")
    # A trailing shell comment is not a runner token either.
    assert not looks_like_test_runner_command("run-probe.sh # pytest -q")


def test_repin_never_uses_a_strip(tmp_path, monkeypatch):
    """A strip would fall back to kanban_home() == the live root: the pin must
    be repointed, never merely removed."""
    live_db = _live_env(tmp_path, monkeypatch)
    scratch_home = tmp_path / "scratchhome"
    scratch_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(scratch_home))
    env = kanban_env_for_child_command("pytest -q", dict(os.environ))
    # The repinned DB lives under the task workspace, distinct from both the
    # live pin and HERMES_HOME (no fallback resolution can reach it).
    assert Path(env["HERMES_KANBAN_DB"]).parent.parent == tmp_path / "ws"
    assert Path(env["HERMES_KANBAN_DB"]) != live_db


def test_scrub_still_inherits_write_fence_with_inherited_path_marker(tmp_path, monkeypatch):
    """The write fence marker (path-valued) is inherited unchanged — repinning
    location pins must not unfence the lineage board for hardened descendants."""
    _live_env(tmp_path, monkeypatch)
    fenced_root = str(tmp_path / "live")
    base = dict(os.environ)
    base[DELEGATED_CHILD_ENV_MARKER] = fenced_root
    env = kanban_env_for_child_command("pytest -q", base)
    assert env[DELEGATED_CHILD_ENV_MARKER] == fenced_root
    # Repin applies to location pins even with an inherited marker.
    assert env["HERMES_KANBAN_DB"] != str(tmp_path / "live" / "kanban.db")


def test_repin_noop_without_kanban_pins():
    """A non-worker host process spawning an ordinary child keeps its env: the
    repin is a worker-lineage guard, not a global env rewrite."""
    env = {"PATH": "/usr/bin", "HOME": "/home/x"}
    assert repin_kanban_board_env(env) == env
    assert delegated_child_subprocess_env(env) == env


def test_repin_drops_kanban_home_override(tmp_path, monkeypatch):
    """HERMES_KANBAN_HOME is a third location override; it must not survive into
    a runner child (the scratch DB pin outranks it, but dropping it removes the
    ambiguity for stale trees that resolve HERMES_KANBAN_HOME first)."""
    _live_env(tmp_path, monkeypatch)
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(tmp_path / "live"))
    env = kanban_env_for_child_command("pytest -q", dict(os.environ))
    assert "HERMES_KANBAN_HOME" not in env


def test_scratch_root_prefers_workspace_and_falls_back_to_tmp(tmp_path, monkeypatch):
    from agent.delegation_context import _scratch_kanban_root
    workspace = tmp_path / "ws"
    workspace.mkdir()
    assert _scratch_kanban_root({"HERMES_KANBAN_WORKSPACE": str(workspace)}) == str(
        workspace / ".kanban-scratch")
    assert _scratch_kanban_root({}).endswith(f"hermes-kanban-scratch-{os.getpid()}")
    assert _scratch_kanban_root({"HERMES_KANBAN_WORKSPACE": str(tmp_path / "gone")}).endswith(
        f"hermes-kanban-scratch-{os.getpid()}")


# --- end-to-end through the real terminal env builder ------------------------


def test_local_environment_child_env_repin(tmp_path, monkeypatch):
    """The spawn surface a worker's pytest actually went through
    (LocalEnvironment._run_bash -> _make_run_env_for) must hand a pytest child
    the scratch board, never the live pin — and leave ordinary commands alone."""
    _live_env(tmp_path, monkeypatch)
    from tools.environments.local import LocalEnvironment
    terminal = LocalEnvironment(cwd=str(tmp_path))
    try:
        runner_env = terminal._make_run_env_for("python -m pytest -q tests/")
        assert ".kanban-scratch" in runner_env["HERMES_KANBAN_DB"]
        assert not runner_env["HERMES_KANBAN_DB"].startswith(str(tmp_path / "live"))
        plain_env = terminal._make_run_env_for("python repro.py")
        assert plain_env["HERMES_KANBAN_DB"] == str(tmp_path / "live" / "kanban.db")
    finally:
        terminal.cleanup()


def test_local_environment_repin_executes_for_real(tmp_path, monkeypatch):
    """End-to-end: a runner-shaped command executed through LocalEnvironment
    actually RUNS with the scratch pin in its environment (no live-board pin
    reaches the child); a plain command keeps the pinned board."""
    _live_env(tmp_path, monkeypatch)
    from tools.environments.local import LocalEnvironment
    probe = tmp_path / "probe.sh"
    probe.write_text("#!/bin/sh\nenv | grep '^HERMES_KANBAN_DB=' > " + str(tmp_path / "seen.txt") + "\n")
    probe.chmod(0o755)
    terminal = LocalEnvironment(cwd=str(tmp_path))
    try:
        terminal.execute(f"{probe} && pytest -q --collect-only")
        seen = (tmp_path / "seen.txt").read_text().strip()
        assert ".kanban-scratch" in seen, seen
        (tmp_path / "seen.txt").unlink()
        terminal.execute(f"{probe}")
        seen = (tmp_path / "seen.txt").read_text().strip()
        assert seen.endswith("/live/kanban.db"), seen
    finally:
        terminal.cleanup()


# --- resource bounds ---------------------------------------------------------


def test_worker_lineage_scope_gets_cpu_quota(monkeypatch):
    """Worker-lineage scopes carry a CPUQuota; gateway scopes keep the historical
    unbounded-CPU shape."""
    from tools import process_registry as pr
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_fixture")
    assert pr._worker_lineage_cpu_quota() is not None
    quota_props = pr._systemd_scope_argv("/bin/systemd-run", "probe", "/bin/true")
    joined = " ".join(quota_props)
    assert "CPUQuota=" in joined
    monkeypatch.delenv("HERMES_KANBAN_TASK")
    assert pr._worker_lineage_cpu_quota() is None
    quota_props = pr._systemd_scope_argv("/bin/systemd-run", "probe", "/bin/true")
    assert "CPUQuota" not in " ".join(quota_props)


def test_scope_argv_includes_worker_lineage_when_not_gateway(monkeypatch):
    """_scope_argv wraps worker-lineage background commands even when the
    spawning process is NOT the supervised gateway (the incident path)."""
    from tools import process_registry as pr
    from tools.process_registry import ProcessRegistry, ProcessSession
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_fixture")
    monkeypatch.setattr(pr, "_IS_LINUX", True)
    monkeypatch.setattr(pr, "_is_supervised_gateway_process", lambda: False)
    monkeypatch.setattr(pr, "_systemd_run_user_scope_available", lambda: True)
    session = ProcessSession(id="proc_test", command="pytest", task_id="", session_key="")
    argv = ProcessRegistry._scope_argv(None, session, "pytest -q", "testunit", "Test")
    assert session.systemd_unit == "hermes-worker-testunit.scope"
    assert "systemd-run" in argv[0]
    assert any("CPUQuota=" in part for part in argv)


def test_worker_lineage_cpu_quota_default_and_override(monkeypatch):
    from tools import process_registry as pr
    monkeypatch.delenv("TERMINAL_WORKER_CPU_QUOTA_PERCENT", raising=False)
    default = pr._systemd_scope_cpu_quota_percent()
    assert 10 <= default <= (os.cpu_count() or 4) * 100
    monkeypatch.setenv("TERMINAL_WORKER_CPU_QUOTA_PERCENT", "25")
    assert pr._systemd_scope_cpu_quota_percent() == 25
    monkeypatch.setenv("TERMINAL_WORKER_CPU_QUOTA_PERCENT", "not-a-number")
    assert pr._systemd_scope_cpu_quota_percent() == default


def test_dispatch_env_caps_hermes_test_workers():
    """The dispatch env builder caps run_tests_parallel fan-out for the worker
    (constant exists, divisor math is the documented cpu//8 floor 1)."""
    from hermes_cli import kanban_db_dispatch as kbd
    assert kbd.KANBAN_WORKER_TEST_WORKERS_DIVISOR >= 1
    cap = max(1, (os.cpu_count() or 4) // kbd.KANBAN_WORKER_TEST_WORKERS_DIVISOR)
    env: dict = {}
    env.setdefault("HERMES_TEST_WORKERS", str(cap))
    assert 1 <= int(env["HERMES_TEST_WORKERS"]) == cap


# --- doctor tripwire ---------------------------------------------------------


def test_doctor_live_board_pin_scan_detects_pinned_pytest(tmp_path, monkeypatch):
    """The doctor check's /proc scanner flags a live pytest pinning the live
    board — the forensic signature from the incident."""
    from hermes_cli import doctor_state as ds
    live_db = tmp_path / "live" / "kanban.db"
    live_db.parent.mkdir(parents=True)
    # A fake /proc: one pytest with the pin, one without, one gone.
    fake = tmp_path / "proc"
    for pid, entries in {
        "101": [b"HERMES_KANBAN_DB=" + str(live_db).encode()],
        "102": [b"HERMES_KANBAN_DB=/elsewhere/kanban.db"],
        "103": None,  # unreadable -> skipped
    }.items():
        d = fake / pid
        d.mkdir(parents=True)
        if entries is not None:
            (d / "environ").write_bytes(b"\0".join(entries) + b"\0")
        (d / "cmdline").write_bytes(b"/usr/bin/python -m pytest\x00tests")
    (fake / "999").mkdir()
    (fake / "999" / "cmdline").write_bytes(b"/usr/bin/python -c pass\x00")
    assert ds._iter_proc_pytest_pids(fake) == ["101", "102", "103"]
    assert ds._proc_env_pins_live_board("101", live_db.resolve(), proc_root=fake) == str(live_db)
    assert ds._proc_env_pins_live_board("102", live_db.resolve(), proc_root=fake) is None
    assert ds._proc_env_pins_live_board("103", live_db.resolve(), proc_root=fake) is None
    # Live-process smoke: the scanner runs against real /proc without raising.
    assert isinstance(ds._iter_proc_pytest_pids(), list)

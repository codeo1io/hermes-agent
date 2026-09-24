"""Regression: recurrence #4 of the wave-9 family live-board leak (2026-09-23
21:40 UTC, 33 fixture-debris rows), this time via a STALE-BASE conductor
validation lane.

The shipped guard stack (resolver fix + ``_ensure_test_isolation`` choke in
``hermes_cli.kanban_db_connect``) cannot help when the *checkout base
predates the guard commits*: hermes-conductor's local validation gate runs
broad suites from its own worktrees, and a lane whose base is
``bcf55bbaed`` (09-21) carries ZERO ``_ensure_test_isolation`` references —
the guard-absent topology recurs by checkout age, not by code regression.

This file pins three invariants against the real platform root:

* the FULL fixture-debris signature (every (title, assignee) tuple seen
  across incidents t_66f2bde0 / t_5d1fe8f9 / t_e2e729a0 / t_68920031 —
  2026-09-23 burst: 33 rows) leaves ZERO rows on the live board when the
  fixture-bearing test files run under the incident topology (TMPDIR under
  the real root, no HERMES_KANBAN_* pins);
* a GATE-SIMULATED run (a stale-base-equivalent subprocess: no guard pins,
  TMPDIR parked under the real root) likewise leaves the live board with
  zero new signature rows;
* the sweep is RED-safe: this file never writes the live board itself; it
  only reads it (read-only URI) and asserts absence. Pre-existing signature
  rows (the completed forensics cards t_66f2bde0/t_68920031/t_bc488882/
  t_c32e41fe) are recorded before the run and tolerated, mirroring the
  wave-9 file's ``allowed`` pattern.

Companion conductor-side hardening: hermes-conductor's
``scripts/local_validation_gate.py`` refuses hermes-agent full suites from
bases older than the guard fix, and pins the whole gate to a scratch board
via env — the version-independent containment. See that repo's
``tests/test_local_resource_policy.py``.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from hermes_state_guard import _real_platform_state_root

_REPO = Path(__file__).resolve().parents[2]

# The exact fixture (title, assignee) tuples observed across the four
# incidents; kept byte-compatible with the board-side sentinel
# ~/.hermes/scripts/kanban_fixture_debris_sentinel.py (FIXTURE_SIGNATURES).
# Sources in this repo:
#   tests/hermes_cli/test_kanban_per_profile_cap.py (a0-a4/alpha, b0-b2/beta)
#   tests/hermes_cli/test_kanban_default_assignee.py + test_kanban_boards.py (t1)
#   tests/hermes_cli/test_kanban_pr_acceptance.py (Publish/publish, missing/
#     stale/head_change, race, local)
#   tests/hermes_cli/test_kanban_review_surfaces.py (review, CLI redaction,
#     direct redaction, not review) + test_kanban_review_lifecycle_complete.py
FIXTURE_SIGNATURES: frozenset[tuple[str, str | None]] = frozenset({
    ("t1", "default"), ("t1", "dev"), ("t1", None),
    ("a0", "alpha"), ("a1", "alpha"), ("a2", "alpha"),
    ("a3", "alpha"), ("a4", "alpha"),
    ("b0", "beta"), ("b1", "beta"), ("b2", "beta"),
    ("Publish", None), ("Publish", "default"), ("Publish", "dev"),
    ("publish", None), ("publish", "default"),
    ("missing", None), ("stale", None), ("head_change", None),
    ("race", None), ("local", None),
    ("review", None), ("review", "builder"), ("review", "default"),
    ("CLI redaction", None), ("CLI redaction", "builder"),
    ("direct redaction", None), ("direct redaction", "builder"),
    ("not review", None), ("not review", "builder"),
})

# Every fixture-bearing file implicated in the 2026-09-23 33-row burst. The
# sweep runs them all in ONE pytest subprocess, as a real full-suite lane
# would — the wave-9 file only replays the two per-profile-cap files.
_SWEEP_FILES = (
    "tests/hermes_cli/test_kanban_default_assignee.py",
    "tests/hermes_cli/test_kanban_boards.py",
    "tests/hermes_cli/test_kanban_pr_acceptance.py",
    "tests/hermes_cli/test_kanban_review_surfaces.py",
    "tests/hermes_cli/test_kanban_review_lifecycle_complete.py",
    "tests/hermes_cli/test_kanban_db.py",
)


def _run_sweep_files(env: dict[str, str], *, per_file: bool) -> list[tuple[str, int, str]]:
    """Run the sweep files as real pytest subprocesses. ``per_file`` mirrors
    the canonical full-suite topology (``scripts/run_tests_parallel.py``:
    one fresh interpreter per file — the only isolation boundary that
    actually matters, and what CI runs); when False, all files share one
    process (the naive topology a bare ``pytest tests/`` invocation gets).

    Returns [(file, returncode, stdout)] so callers can distinguish
    "the lane failed" from "fixture rows leaked" — host-specific
    pre-existing failures (e.g. no systemd user bus) must not be conflated
    with the leak invariant. The FULL stdout is kept: per-failure
    classification (below) needs each failure's own traceback, not a tail.
    """
    out: list[tuple[str, int, str]] = []
    groups: list[list[str]] = (
        [[f] for f in _SWEEP_FILES] if per_file else [list(_SWEEP_FILES)]
    )
    for group in groups:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *group, "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=_REPO,
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
        )
        out.append((" ".join(group), result.returncode, result.stdout))
    return out


def _child_env(tmpdir: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("PYTEST_CURRENT_TEST", "PYTEST_VERSION", "HERMES_TEST_ISOLATION")
    }
    env["PYTEST_CURRENT_TEST"] = (
        "tests/hermes_cli/test_kanban_fixture_debris_recurrence4_sweep.py::child"
    )
    env["TMPDIR"] = str(tmpdir)
    return env


def _live_signature_rows(live: Path) -> list[tuple[str, str, str | None, str | None]]:
    """Read-only probe of the live board for the fixture signature."""
    conn = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
    try:
        titles = {t for t, _ in FIXTURE_SIGNATURES}
        out = []
        for tid, title, assignee, created_by in conn.execute(
            "SELECT id, title, assignee, created_by FROM tasks WHERE title IN "
            f"({','.join('?' * len(titles))})",
            tuple(sorted(titles)),
        ):
            if (title, assignee) in FIXTURE_SIGNATURES:
                out.append((tid, title, assignee, created_by))
        return out
    finally:
        conn.close()


@pytest.fixture
def debris_topology(_hermetic_environment, monkeypatch, tmp_path):
    """Recurrence-#4 topology: TMPDIR under the REAL root (conductor gate
    exports it for every step), no HERMES_KANBAN_* pins anywhere."""
    root = _real_platform_state_root()
    assert root is not None, "platform state root must resolve for this regression"
    tmpdir = root / "tmp" / "recurrence4-regression"
    tmpdir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    for var in (
        "HERMES_KANBAN_DB",
        "HERMES_KANBAN_HOME",
        "HERMES_KANBAN_BOARD",
        "HERMES_KANBAN_WORKSPACES_ROOT",
        "HERMES_KANBAN_GUARD_BYPASS",
    ):
        monkeypatch.delenv(var, raising=False)
    return root, tmpdir


def _host_artifact_failures(results: list[tuple[str, int, str]]) -> list[tuple[str, int, str]]:
    """Lanes whose failure text matches ONLY host-specific pre-existing
    artifacts (this runner has no systemd user session: the dispatcher
    spawn-env tests fail here but pass in CI) are not lane-health signals."""
    artifact_tests = (
        "TestWorkerSpawnEnv::test_default_spawn_sets_env_vars",
        "test_dispatcher_spawn_injects_kanban_paths_without_stale_session",
    )
    # The base's own connect-time choke (RuntimeError raised by the kanban or
    # state live-system guard refusing a production path under the real root)
    # is the containment working, not a lane defect — but only for the
    # failure it actually explains. Matched PER FAILURE (round-1 review):
    # the previous lane-wide ``not all(s in tail ...)`` test excused EVERY
    # unknown failure in any lane that merely showed one guard choke
    # anywhere in its output.
    choke_signatures = (
        ("kanban_db_connect.py", "kanban test-isolation guard"),
        ("hermes_state.py", "live-system guard"),
    )

    def _failure_blocks(stdout: str) -> dict[str, str]:
        """Map each FAILED test id to the traceback of ITS OWN failure
        section. ``pytest -q`` prints failures as ``_<id>`` headers followed
        by the traceback, so a failure is choke-explained only when the
        guard's file+message tokens appear between its header and the next
        failure header — never because a sibling failure choked."""
        blocks: dict[str, str] = {}
        current_id: str | None = None
        lines: list[str] = []
        for line in stdout.splitlines():
            if line.startswith("____") and line.endswith("____"):
                if current_id is not None:
                    blocks[current_id] = "\n".join(lines)
                # header shape: ____ test_file.py::test_name ____
                current_id = line.strip("_").strip()
                lines = []
            elif current_id is not None:
                lines.append(line)
        if current_id is not None:
            blocks[current_id] = "\n".join(lines)
        return blocks

    out = []
    for fname, code, stdout in results:
        if code == 0:
            continue
        blocks = _failure_blocks(stdout)
        failed_lines = [l for l in stdout.splitlines() if l.startswith("FAILED ")]
        unknown = []
        for line in failed_lines:
            test_id = line[len("FAILED "):].split(" - ")[0].strip()
            if any(a in line for a in artifact_tests):
                continue
            block = blocks.get(test_id, "")
            if any(all(s in block for s in sig) for sig in choke_signatures):
                continue
            unknown.append(line)
        if unknown:
            out.append((fname, code, "\n".join(unknown)))
    return out


def test_full_signature_sweep_leaves_live_board_clean(debris_topology):
    """The whole fixture-debris signature, run under the incident topology
    (TMPDIR under the real root, no pins), must leave ZERO new signature
    rows on the live board — per file, mirroring the canonical full-suite
    runner (``scripts/run_tests_parallel.py``)."""
    root, tmpdir = debris_topology
    live = root / "kanban.db"
    if not live.exists():
        pytest.skip("no live board on this host (not the runner machine)")

    allowed = set(_live_signature_rows(live))
    results = _run_sweep_files(_child_env(tmpdir), per_file=True)

    new_rows = [row for row in _live_signature_rows(live) if row not in allowed]
    assert not new_rows, f"fixture rows reached the live board: {new_rows}"
    # Lane health is asserted only AFTER the leak invariant: a host-specific
    # pre-existing failure must surface as its own red, never silently
    # green the sweep.
    failed = _host_artifact_failures(results)
    assert not failed, f"sweep lane failed: {failed}"


def test_stale_base_gate_lane_is_neutralized(debris_topology):
    """The conductor-side hardening: a gate lane on the incident's STALE BASE
    (bcf55bbaed — zero _ensure_test_isolation refs) must leave the live board
    untouched. The gate now refuses such bases outright (fail-closed), so the
    simulation here proves the SECOND belt: even when a stale-base lane runs,
    the scratch-home + scratch-board pin the gate injects keeps every fixture
    row off the live board."""
    root, tmpdir = debris_topology
    live = root / "kanban.db"
    if not live.exists():
        pytest.skip("no live board on this host (not the runner machine)")

    allowed = set(_live_signature_rows(live))

    # Simulate the gate's sandbox: a scratch HOME + HERMES_HOME + TMPDIR
    # triple parked UNDER the real root (worst case: the collapse bug maps
    # it back onto the production root) + the gate-injected scratch-board pin.
    scratch = tmpdir / "gate-scratch-home"
    scratch.mkdir(parents=True, exist_ok=True)
    env = _child_env(tmpdir)
    env["HOME"] = str(scratch)
    env["HERMES_HOME"] = str(scratch / ".hermes")
    # The gate-injected pin: the whole lane writes only this scratch board.
    env["HERMES_KANBAN_DB"] = str(scratch / "scratch-kanban.db")
    results = _run_sweep_files(env, per_file=True)

    # The current conftest strips HERMES_KANBAN_* per test, so fixture DBs
    # land under the TMPDIR sandbox homes — exactly the wave-9 topology. The
    # invariant is where they do NOT land: the live board must be untouched.
    new_rows = [row for row in _live_signature_rows(live) if row not in allowed]
    assert not new_rows, f"stale-base lane leaked fixture rows: {new_rows}"
    failed = _host_artifact_failures(results)
    assert not failed, f"sweep lane failed under the gate sandbox: {failed}"


def test_pre_existing_forensics_cards_are_the_only_signature_rows(debris_topology):
    """Pin the baseline: outside the four known forensics/inspection cards,
    the live board carries no fixture-signature rows. If this fails, the
    sentinel should have swept or the family leaked again — either way the
    baseline for the sweeps above is contaminated and must be re-baselined
    deliberately, not silently."""
    root, _ = debris_topology
    live = root / "kanban.db"
    if not live.exists():
        pytest.skip("no live board on this host (not the runner machine)")
    rows = _live_signature_rows(live)
    known = {"t_c32e41fe", "t_66f2bde0", "t_68920031", "t_bc488882"}
    unknown = [r for r in rows if r[0] not in known]
    assert not unknown, (
        f"live board carries unexpected fixture-signature rows outside the "
        f"known forensics cards: {unknown} — re-baseline deliberately"
    )


# ── per-failure choke classification (round-1 review, item a) ────────────────

def test_host_artifact_failures_classifies_per_failure_not_per_lane():
    """A guard choke explains only the failure whose OWN traceback carries
    it. The pre-2026-09-24 lane-wide ``not all(s in tail ...)`` test excused
    every unknown failure in any lane that showed one choke anywhere."""
    from tests.hermes_cli.test_kanban_fixture_debris_recurrence4_sweep import (
        _host_artifact_failures,
    )

    choked = (
        "__________ tests/hermes_cli/test_kanban_boards.py::test_x __________\n"
        "hermes_cli/kanban_db_connect.py:733: RuntimeError: kanban "
        "test-isolation guard: test attempted to open the production kanban "
        "DB (under real Hermes root /home/agent/.hermes)\n"
    )
    unrelated = (
        "__________ tests/hermes_cli/test_kanban_boards.py::test_y __________\n"
        "E       AssertionError: boom\n"
    )
    stdout = (
        f"{choked}{unrelated}"
        "=========================== short test summary info ============\n"
        "FAILED tests/hermes_cli/test_kanban_boards.py::test_x\n"
        "FAILED tests/hermes_cli/test_kanban_boards.py::test_y\n"
    )
    results = [("tests/hermes_cli/test_kanban_boards.py", 1, stdout)]

    # Both failures present: the unknown one must surface.
    assert _host_artifact_failures(results), "unrelated failure must not be excused"
    # Only the choke failure: the lane is explainable, nothing surfaces.
    choke_only = (
        f"{choked}"
        "=========================== short test summary info ============\n"
        "FAILED tests/hermes_cli/test_kanban_boards.py::test_x\n"
    )
    assert not _host_artifact_failures(
        [("tests/hermes_cli/test_kanban_boards.py", 1, choke_only)]
    )
    # Passing lanes are never flagged.
    assert not _host_artifact_failures(
        [("tests/hermes_cli/test_kanban_boards.py", 0, "")]
    )
    # The dispatcher spawn-env artifact tests stay excused by id.
    artifact_only = (
        "=========================== short test summary info ============\n"
        "FAILED tests/hermes_cli/test_kanban_boards.py::"
        "TestWorkerSpawnEnv::test_default_spawn_sets_env_vars\n"
    )
    assert not _host_artifact_failures(
        [("tests/hermes_cli/test_kanban_boards.py", 1, artifact_only)]
    )
    # A live-system guard choke (state DB family) is also per-failure known.
    state_choke = (
        "__________ tests/hermes_cli/test_kanban_boards.py::test_z __________\n"
        "hermes_state.py:206: RuntimeError: live-system guard: test "
        "attempted to open production state.db (under real Hermes root "
        "/home/agent/.hermes)\n"
        "=========================== short test summary info ============\n"
        "FAILED tests/hermes_cli/test_kanban_boards.py::test_z\n"
    )
    assert not _host_artifact_failures(
        [("tests/hermes_cli/test_kanban_boards.py", 1, state_choke)]
    )

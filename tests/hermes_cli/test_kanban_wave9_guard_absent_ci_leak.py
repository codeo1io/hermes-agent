"""Regression: the 2026-09-18 wave-9 live-board leak (fixture rows written by
fork-CI pytest through a GUARD-ABSENT checkout).

Wave 9 (06:26-06:27 UTC, 24 rows: a0-a4/b0-b2 alpha/beta x4 bursts + two "t1"
assignee=default rows) was NOT a bypass of the choke-point guard: the leaking
CI job ran refs/pull/26/merge (6faf40d5) whose tree has ZERO
``_ensure_test_isolation`` — the guard-present refs/pull/25/merge checkout
(e7b48822) only landed in the workspace nine minutes AFTER the burst. Two
preconditions composed on the guard-absent base:

1. The self-hosted runner exports ``TMPDIR=/home/agent/.hermes/tmp/<runner>``
   for every job step, so ``tempfile.mkdtemp`` sandboxes — including the
   ``kanban_per_profile_cap_test_*`` / ``kanban_default_assignee_test_*``
   fixture homes — land UNDER the platform-native Hermes root.
2. The pre-fix ``hermes_constants.get_default_hermes_root()`` collapsed ANY
   ``HERMES_HOME`` under the native root onto the native root itself, so
   ``kanban_home()`` resolved those sandboxes to the PRODUCTION board.

This file pins the whole topology against the REAL platform root:

* the collapsed resolution is gone — a sandbox under the real root stays a
  sandbox (``get_default_hermes_root`` / ``kanban_home`` / ``kanban_db_path``);
* even if every path resolver regressed, the connect-time choke refuses the
  live board from a test context (belt to the resolver's braces);
* end-to-end: the two named wave-9 test FILES, run as real pytest subprocesses
  under the incident topology (TMPDIR under the real root, no pins), leave the
  live board byte-identical and write their rows only inside the sandbox.
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
_WAVE9_FILES = (
    "tests/hermes_cli/test_kanban_per_profile_cap.py",
    "tests/hermes_cli/test_kanban_default_assignee.py",
)


@pytest.fixture
def wave9_ci_topology(_hermetic_environment, monkeypatch, tmp_path):
    """Replay the wave-9 CI step env: TMPDIR parked UNDER the real root, no
    HERMES_KANBAN_* pins anywhere (the burst processes carried none)."""
    root = _real_platform_state_root()
    assert root is not None, "platform state root must resolve for this regression"
    tmpdir = root / "tmp" / "wave9-regression"
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


def _sandbox_fixture_dbs(root: Path) -> list[Path]:
    """The kanban.db files the wave-9 fixtures created under TMPDIR — the only
    place wave-9 rows may exist. Returns every match."""
    candidates = sorted(
        (root / "tmp").glob("wave9-regression/kanban_*_test_*/kanban.db"),
        key=lambda p: p.stat().st_mtime,
    )
    assert candidates, "fixtures never created their sandbox DBs"
    return candidates


def test_sandbox_under_real_root_resolves_to_itself(wave9_ci_topology):
    """Precondition 2 is dead: HERMES_HOME under the native root (and not a
    ``profiles/<name>`` home) must resolve as its own root, never collapse to
    the production board root."""
    import tempfile

    from hermes_constants import get_default_hermes_root
    from hermes_cli import kanban_db as kb

    root, _ = wave9_ci_topology
    # tempfile caches its tempdir at first use, so set it explicitly to the
    # fixture's TMPDIR — the mkdtemp sandbox must land under the real root.
    import tempfile

    tempfile.tempdir = os.environ["TMPDIR"]
    sandbox = Path(tempfile.mkdtemp(prefix="kanban_per_profile_cap_test_"))
    tempfile.tempdir = None
    assert sandbox.resolve().is_relative_to(root), "test premise: sandbox under the real root"
    os.environ["HERMES_HOME"] = str(sandbox)
    try:
        resolved_root = get_default_hermes_root()
        assert resolved_root == sandbox.resolve(), (
            f"get_default_hermes_root() collapsed {sandbox} onto the real root "
            f"{resolved_root} — the wave-9 leak is back"
        )
        assert kb.kanban_home() == sandbox.resolve()
        assert kb.kanban_db_path() == sandbox.resolve() / "kanban.db"
    finally:
        os.environ.pop("HERMES_HOME", None)


def test_choke_refuses_live_board_from_test_context(wave9_ci_topology):
    """Belt: even with every resolver regressed, the connect-time choke must
    refuse the production board before any sqlite touch."""
    from hermes_cli import kanban_db_connect as kbc

    root, _ = wave9_ci_topology
    before = (root / "kanban.db").stat().st_mtime_ns
    with pytest.raises(RuntimeError, match="test-isolation guard"):
        kbc._ensure_test_isolation(root / "kanban.db")
    assert (root / "kanban.db").stat().st_mtime_ns == before


def test_wave9_files_write_zero_live_board_rows_end_to_end(wave9_ci_topology):
    """The named wave-9 test files, run as real pytest subprocesses under the
    incident topology (TMPDIR under the real root, inherited-by-nothing), must
    pass AND leave the live board byte-identical. Their fixture rows may exist
    only inside the sandbox DB the fixture created."""
    root, _ = wave9_ci_topology
    live = root / "kanban.db"
    if not live.exists():
        pytest.skip("no live board on this host (not the runner machine)")
    # The live board is a BUSY production DB (real workers heartbeat into it
    # every few seconds), so global mtime/size is not a stable signal. Scope
    # the leak assertion to exactly the wave-9 fingerprint rows.
    def _live_wave_rows() -> list[tuple]:
        conn = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
        try:
            return conn.execute(
                "SELECT id, title, assignee, created_by FROM tasks WHERE title IN "
                "(?,?,?,?,?,?,?,?,?) AND created_by IS NULL",
                wave_titles,
            ).fetchall()
        finally:
            conn.close()

    wave_titles = ("a0", "a1", "a2", "a3", "a4", "b0", "b1", "b2", "t1")
    before_rows = _live_wave_rows()
    # The swept wave-9 rows are gone; the one surviving "t1" is the forensics
    # card the sweep left by design. Record it so the assertion is exact.
    allowed = set(before_rows)

    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("PYTEST_CURRENT_TEST", "PYTEST_VERSION", "HERMES_TEST_ISOLATION")
    }
    env["PYTEST_CURRENT_TEST"] = (
        "tests/hermes_cli/test_kanban_wave9_guard_absent_ci_leak.py::child"
    )
    env["TMPDIR"] = os.environ["TMPDIR"]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *_WAVE9_FILES, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=_REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"wave-9 files failed under the incident topology\n"
        f"stdout tail: {result.stdout[-2000:]}\nstderr tail: {result.stderr[-2000:]}"
    )

    after_rows = _live_wave_rows()
    new_rows = [row for row in after_rows if row not in allowed]
    assert not new_rows, f"fixture rows reached the live board: {new_rows}"

    sandbox_dbs = _sandbox_fixture_dbs(root)
    titles: set[str] = set()
    for db in sandbox_dbs:
        sconn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            titles.update(
                row[0]
                for row in sconn.execute(
                    "SELECT DISTINCT title FROM tasks WHERE assignee IN ('alpha','beta','default')"
                )
            )
        finally:
            sconn.close()
    assert {"a0", "a1", "a2", "b0", "b1", "b2"} <= titles, (
        f"fixture rows missing from the sandbox DBs {[str(p) for p in sandbox_dbs]}: "
        f"{sorted(titles)}"
    )
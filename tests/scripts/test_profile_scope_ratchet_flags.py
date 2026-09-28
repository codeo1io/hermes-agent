"""Contract tests for the tree-wide profile-scope lint flags added for the
P05 ratchet gate (rm-031): ``--all``, ``--pattern``, ``--exclude``, ``--max-findings``.

These assert *relationships between modes and filters*, never a frozen finding
count (that would be a change-detector): the filtered run must equal the client-side
filter of the unfiltered run, and the exit code must follow the budget relation
deterministically at whatever count the tree currently has.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_profile_scope_patterns.py"

# The rm-028 fix's acceptance criterion: whole-file scan of each unbound spawn is clean.
RM_028_FILES = [
    "plugins/platforms/buzz/adapter.py",
    "plugins/platforms/photon/adapter.py",
    "plugins/memory/openviking/__init__.py",
]

EXCLUDED_ROOTS = ("tests", "evals", "scripts", "skills")


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def _run_json(tmp_path: Path, name: str, *args: str) -> tuple[list[dict], subprocess.CompletedProcess]:
    out = tmp_path / name
    proc = _run(*args, "--json", str(out))
    assert proc.returncode in (0, 1), proc.stderr
    return json.loads(out.read_text()), proc


def test_pattern_filter_equals_client_side_filter(tmp_path):
    # The --pattern flag must be exactly a pattern_id filter over the same run —
    # a relationship that holds whether the tree has 0 or 50 P05 sites.
    all_f, _ = _run_json(tmp_path, "all.json", "--all")
    p05_f, _ = _run_json(tmp_path, "p05.json", "--all", "--pattern", "P05")

    assert p05_f == [f for f in all_f if f["pattern_id"] == "P05"]
    assert all(f["pattern_id"] == "P05" for f in p05_f)


def test_exclude_drops_only_excluded_roots(tmp_path):
    args = ["--all", "--pattern", "P05"]
    all_f, _ = _run_json(tmp_path, "noex.json", *args)
    ex_f, _ = _run_json(tmp_path, "ex.json", *args, "--exclude", *EXCLUDED_ROOTS)

    prefixes = tuple(f"{root}/" for root in EXCLUDED_ROOTS)
    assert ex_f == [f for f in all_f if not f["path"].startswith(prefixes)]


def test_max_findings_budget_is_a_ratchet_not_a_snapshot(tmp_path):
    # The budget is a relation (count <= budget -> exit 0), not a snapshot: the
    # contract stays meaningful at whatever count the tree has, including 0.
    findings, _ = _run_json(
        tmp_path, "count.json", "--all", "--pattern", "P05", "--exclude", *EXCLUDED_ROOTS)
    count = len(findings)

    base = ["--all", "--pattern", "P05", "--exclude", *EXCLUDED_ROOTS]
    within = _run(*base, "--max-findings", str(count + 5))
    assert within.returncode == 0, within.stdout + within.stderr

    at_edge = _run(*base, "--max-findings", str(count))
    assert at_edge.returncode == 0, at_edge.stdout + at_edge.stderr

    if count > 0:  # below-budget must fail exactly when findings exist
        below = _run(*base, "--max-findings", str(count - 1))
        assert below.returncode == 1
        assert "> budget" in below.stdout


@pytest.mark.parametrize("repo_file", RM_028_FILES)
def test_files_mode_rm028_surfaces_are_clean(repo_file):
    # The pre-existing per-PR mode keeps working, and the three rm-028 spawns
    # now scan clean whole-file (the fix's own acceptance criterion).
    proc = _run("--files", repo_file)
    assert proc.returncode == 0, proc.stdout + proc.stderr

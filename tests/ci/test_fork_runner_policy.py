"""Fork CI runner-policy guard (v0.22.4 adoption).

Fork doctrine (#270, and the #508 un-wedge): this public fork runs on
GitHub-hosted runners ONLY. Upstream migrated to Blacksmith (paid third-party)
runner labels and ``useblacksmith/*`` action forks between v0.21.7 and
v0.22.4; a naive adoption merge re-introduces billing-blocked labels through
the ~37 workflow files that auto-merge cleanly, and every CI lane queues
forever. This guard fails on ANY non-GitHub-hosted runner label or
Blacksmith action ref anywhere under .github/workflows — including files a
merge touched only by auto-merge.
"""
from __future__ import annotations

import re
from pathlib import Path

FORBIDDEN_ACTIONS = ("useblacksmith/",)
FORBIDDEN_LABEL_PATTERNS = (
    re.compile(r"blacksmith-", re.IGNORECASE),
    # GitHub larger-runner / paid SKUs historically billing-blocked here.
    re.compile(r"(ubuntu|windows|macos)-latest-\d+-?[a-z]*-?core", re.IGNORECASE),
)
# GitHub-hosted labels (first-party): ubuntu-latest, ubuntu-24.04(-arm),
# windows-latest, macos-latest, macos-15, macos-15-intel, and static matrix
# entries that are not labels at all (e.g. container images). We fail CLOSED
# on the forbidden patterns above rather than enumerating allowed labels.

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _workflow_files() -> list[Path]:
    return sorted(p for p in WORKFLOWS.iterdir() if p.suffix in (".yml", ".yaml"))


def test_workflows_directory_exists_and_has_files():
    files = _workflow_files()
    assert files, "no workflow files found — guard cannot run"


def test_no_blacksmith_action_refs():
    offenders: list[str] = []
    for f in _workflow_files():
        for i, line in enumerate(f.read_text().splitlines(), 1):
            code = line.split("#", 1)[0]
            for bad in FORBIDDEN_ACTIONS:
                if bad in code:
                    offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert not offenders, (
        "fork policy #270 violation — Blacksmith action refs (billing-blocked "
        f"third-party runners):\n" + "\n".join(offenders)
    )


def test_no_paid_or_blacksmith_runner_labels():
    offenders: list[str] = []
    for f in _workflow_files():
        for i, line in enumerate(f.read_text().splitlines(), 1):
            code = line.split("#", 1)[0]
            for pat in FORBIDDEN_LABEL_PATTERNS:
                if pat.search(code):
                    offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert not offenders, (
        "fork policy #270 violation — paid/Blacksmith runner labels "
        f"(billing-blocked on this public fork):\n" + "\n".join(offenders)
    )

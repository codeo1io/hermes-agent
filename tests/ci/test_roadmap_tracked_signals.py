"""ROADMAP.md signals must reference tracked repository paths.

The 2026-10 cycle-1 assessment (N7) caught the roadmap render citing
``.worktrees/t_171b1032/...`` scratch and untracked ``hermes_cli/web_dist/...``
build output as its top-priority signals — the renderer had scanned a dirty
canonical checkout, so two roadmap items were unfalsifiable on any clean
clone. This guard pins the fix: every structured ``kind:path`` signal entry in
ROADMAP.md must name a path that exists in the tree and is tracked by git.
Free-form prose signals (which mention paths inside sentences) are out of
scope: only space-free ``kind:path`` tokens are structured entries.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Structured signal entry: "<wordly-kind>:<path>" with no spaces anywhere,
# e.g. "reliability.no_tests:tools/session_search_tool.py" or
# "reliability.complexity_hot:gateway/run.py::L42".
ENTRY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:([^\s]+)$")
# A path is checkable when it names a location (has a separator) or a file
# with an extension; bare numbers (line refs like ".gitignore:93") are not.
CHECKABLE = re.compile(r"^[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,5}$")
# Renderer truncation suffix on signals lines.
MORE_SUFFIX = re.compile(r"\s*\(\+\d+ more\)\s*$")


def _structured_signal_paths(roadmap: str) -> list[tuple[int, str, str]]:
    """Yield (line_no, entry, path) for every structured kind:path signal."""
    found: list[tuple[int, str, str]] = []
    for line_no, line in enumerate(roadmap.splitlines(), start=1):
        if not line.lstrip().startswith("- signals:"):
            continue
        value = line.split("- signals:", 1)[1]
        value = MORE_SUFFIX.sub("", value)
        for token in value.split(","):
            token = token.strip()
            match = ENTRY.match(token)
            if not match:
                continue
            path = match.group(1)
            path = re.sub(r"::L\d+$", "", path)  # complexity line markers
            if "/" not in path and not CHECKABLE.match(path):
                continue
            found.append((line_no, token, path))
    return found


def _tracked_paths() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {line for line in out.splitlines() if line}


def test_roadmap_exists() -> None:
    assert (REPO_ROOT / "ROADMAP.md").is_file(), "ROADMAP.md must exist at the repo root"


def test_structured_signals_reference_tracked_paths() -> None:
    roadmap_path = REPO_ROOT / "ROADMAP.md"
    entries = _structured_signal_paths(roadmap_path.read_text(encoding="utf-8"))
    tracked = _tracked_paths()

    offenders = [
        f"ROADMAP.md:{line_no}: {entry!r} -> {path!r}"
        for line_no, entry, path in entries
        if path not in tracked or not (REPO_ROOT / path).exists()
    ]
    assert not offenders, (
        "ROADMAP.md signal entries must cite tracked, existing paths "
        "(untracked scratch/build output is unfalsifiable on a clean clone):\n"
        + "\n".join(offenders)
    )


def test_guard_catches_untracked_signals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Behavior contract: phantom entries are flagged, tracked ones pass."""
    sample = (
        "### Item A\n"
        "- id: `rm-900` | track: reliability | priority: 1 | status: candidate\n"
        "- signals: reliability.no_tests:.github/scripts/run-workspace-checks.mjs, "
        "reliability.no_tests:.worktrees/t_9/.github/scripts/run-workspace-checks.mjs\n"
    )
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ROADMAP.md").write_text(sample, encoding="utf-8")
    entries = _structured_signal_paths(sample)
    assert [path for _, _, path in entries] == [
        ".github/scripts/run-workspace-checks.mjs",
        ".worktrees/t_9/.github/scripts/run-workspace-checks.mjs",
    ]

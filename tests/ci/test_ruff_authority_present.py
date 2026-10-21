"""The ruff single-authority contract for this checkout.

History (cycle 2, 2026-10): a salvage/merge composite left main with ZERO ruff
config — the pinned binary was still installed, lint lanes still ran, and
``scripts/check`` reported 42,312 default-rule diagnostics on a tree that the
doctrine config had previously certified clean. These tests pin the doctrine the
fix restored so the class cannot recur silently: exactly one authority
(``ruff.toml``), no ``[tool.ruff]`` shadow in ``pyproject.toml``, and the
authority provably enforced by the pinned binary the health runner resolves.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from scripts.code_health import ruff_runner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# The one sanctioned authority. The doctrine is single-file on purpose: a second
# block in pyproject.toml is how the shadow trap (ruff.toml wins, pyproject
# silently drifts) was born upstream, which still ships both to this day.
AUTHORITY = REPO_ROOT / "ruff.toml"


def test_exactly_one_ruff_authority_exists() -> None:
    assert AUTHORITY.is_file(), (
        "ruff.toml is the single lint authority for this repo and it is gone; "
        "without it the pinned ruff falls back to default rules and the lint "
        "lanes certify the wrong tree"
    )


def test_pyproject_carries_no_tool_ruff_shadow() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert "ruff" not in pyproject.get("tool", {}), (
        "pyproject.toml carries a [tool.ruff] block; ruff.toml takes precedence "
        "over it, so the block can only drift and mislead — the doctrine is "
        "ruff.toml only"
    )


def test_resolved_ruff_matches_the_pyproject_pin() -> None:
    pin = ruff_runner.pinned_version(REPO_ROOT)
    cmd = ruff_runner.resolve_ruff(REPO_ROOT)
    version = subprocess.run(
        [*cmd, "--version"], capture_output=True, text=True, check=True, timeout=120
    ).stdout.strip()
    assert f"ruff {pin}" in version, (
        f"the health runner resolved {cmd} but its output {version!r} does not "
        f"match the pyproject pin ruff=={pin}; rule behaviour drifts between "
        "releases and the enforcement test below would certify the wrong binary"
    )


# A rule from the doctrine's select set that is enforced in tests/** (no
# per-file ignore covers it): subprocess.run without an explicit check=.
_PLW1510_PROBE = "import subprocess\n\ndef probe() -> None:\n    subprocess.run(['true'])\n"
_PLW1510_CLEAN = (
    "import subprocess\n\ndef probe() -> None:\n    subprocess.run(['true'], check=False)\n"
)


def _check_probe(cmd: list[str], source: str) -> str:
    return subprocess.run(
        [*cmd, "check", "--config", str(AUTHORITY),
         "--stdin-filename", "tests/ci/_ruff_authority_probe.py",
         "--output-format", "concise", "-"],
        input=source, capture_output=True, text=True, timeout=300,
    ).stdout


@pytest.mark.parametrize(
    ("source", "expect_finding"),
    [(_PLW1510_PROBE, True), (_PLW1510_CLEAN, False)],
    ids=["offending-source-flagged", "clean-source-passes"],
)
def test_authority_is_enforced_by_the_pinned_ruff(source: str, expect_finding: bool) -> None:
    """The authority must be loadable and DO something, not merely exist.

    The probe pins the doctrine config explicitly, so a pass/fail here
    reflects the config's select set, never ambient settings.
    """
    cmd = ruff_runner.resolve_ruff(REPO_ROOT)
    out = _check_probe(cmd, source)
    flagged = "PLW1510" in out
    assert flagged is expect_finding, (
        f"pinned ruff at {cmd} did not enforce the doctrine as expected on the "
        f"probe source; output was: {out!r}"
    )


def test_doctrine_config_parses_for_the_pinned_binary() -> None:
    """The authority must parse cleanly under the pinned binary (schema drift
    between ruff releases turns the whole lane into one opaque E902 failure)."""
    cmd = ruff_runner.resolve_ruff(REPO_ROOT)
    proc = subprocess.run(
        [*cmd, "check", "--config", str(AUTHORITY), "--statistics",
         "--stdin-filename", "probe.py", "-"],
        input="x = 1\n", capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode in (0, 1), (
        f"pinned ruff failed to parse the doctrine config: rc={proc.returncode}, "
        f"stderr={proc.stderr!r}"
    )

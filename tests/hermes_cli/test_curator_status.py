"""Tests for `hermes curator status` output.

Covers:
- y0shualee's "least recently active" semantic (view/patch/use all count as activity).
- The most-used / least-used rankings by activity_count so users can see which
  skills actually get exercised.
"""

from __future__ import annotations

import io
import os
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path

import pytest


@pytest.fixture
def curator_status_env(tmp_path, monkeypatch):
    """Isolated HERMES_HOME with real agent-created skills on disk."""
    home = tmp_path / ".hermes"
    skills = home / "skills"
    skills.mkdir(parents=True)
    (home / "logs").mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    import importlib
    import hermes_constants
    importlib.reload(hermes_constants)
    from tools import skill_usage
    importlib.reload(skill_usage)
    from agent import curator
    importlib.reload(curator)
    from hermes_cli import curator as curator_cli
    importlib.reload(curator_cli)

    def _write_skill(name: str) -> None:
        d = skills / name
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\n"
            f"name: {name}\n"
            "description: test\n"
            "version: 1.0.0\n"
            "metadata:\n"
            "  hermes:\n"
            "    agent_created: true\n"
            "---\n"
            f"# {name}\n"
        )

    return {
        "home": home,
        "skills": skills,
        "make_skill": _write_skill,
        "skill_usage": skill_usage,
        "curator_cli": curator_cli,
    }


# ---------------------------------------------------------------------------
# Unmanaged blind spot + adopt verb
# ---------------------------------------------------------------------------


def test_list_unmanaged_itemizes_and_explains(curator_status_env):
    """`status` gives the count; this gives the names plus WHY each is
    unmanaged, so the user can decide what to adopt."""
    env = curator_status_env
    env["make_skill"]("legacy-one")
    env["make_skill"]("managed-one")
    env["skill_usage"].mark_agent_created("managed-one")

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = env["curator_cli"]._cmd_list_unmanaged(Namespace())
    out = buf.getvalue()

    assert rc == 0
    assert "legacy-one" in out
    assert "managed-one" not in out
    assert "no marker" in out or "created_by:null" in out
    assert "curator adopt" in out




def test_status_subprocess_contract_canary(tmp_path, monkeypatch):
    """E2E failure-class canary (finding f8c3e3602c81).

    Maestro probes `hermes curator status` as a subprocess with a 45s budget:
    PASS = rc 0 + 'curator: ENABLED' on stdout. The pre-fix scan-loop
    regression intermittently blew that budget under fleet load, so this runs
    the REAL CLI boot path in a subprocess against a temp HERMES_HOME and
    asserts the contract plus a generous wall bound (30s) that catches the
    regression class without flapping when the CI host is busy.
    """
    import subprocess
    import sys
    import time

    home = tmp_path / ".hermes"
    skills = home / "skills"
    skills.mkdir(parents=True)
    (home / "logs").mkdir()
    (home / "config.yaml").write_text("skills: {}\n")
    for i in range(8):
        d = skills / f"canary-skill-{i}"
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"---\nname: canary-skill-{i}\ndescription: canary fixture {i}\n---\n\n# {i}\n"
        )

    repo_root = Path(__file__).resolve().parents[2]
    env = {
        "HERMES_HOME": str(home),
        "HOME": str(tmp_path),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(repo_root),
        "TZ": "UTC",
        "LANG": "C.UTF-8",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    t0 = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(repo_root / "hermes_cli" / "main.py"), "curator", "status"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    elapsed = time.monotonic() - t0

    assert proc.returncode == 0, f"rc={proc.returncode} stderr={proc.stderr[-800:]}"
    assert "curator: ENABLED" in proc.stdout, proc.stdout[:400]
    assert elapsed < 30.0, (
        f"curator status took {elapsed:.1f}s on an 8-skill tree — the scan "
        "regression class is back (probe budget is 45s)"
    )

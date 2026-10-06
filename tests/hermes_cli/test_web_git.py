"""Injection guards for review_rev_parse: a ref string from the dashboard must be resolved as
a rev, never parsed as a git option. Regression class: `rev-parse --exec-path=...` printed the
exec-path string (exit 0) and was returned as if it were a sha."""

import subprocess
from pathlib import Path

from hermes_cli import web_git


def _init_repo(tmp_path: Path) -> str:
    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True,
            env={"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "PATH": "/usr/bin:/bin"},
        )

    (tmp_path / "f.txt").write_text("x\n")
    git("init", "-q", "-b", "main")
    git("add", "f.txt")
    git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "init")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_review_rev_parse_resolves_valid_refs(tmp_path):
    sha = _init_repo(tmp_path)
    assert web_git.review_rev_parse(str(tmp_path), "HEAD") == sha
    assert web_git.review_rev_parse(str(tmp_path), None) == sha
    assert web_git.review_rev_parse(str(tmp_path), sha) == sha


def test_review_rev_parse_rejects_option_string_refs(tmp_path):
    """Regression: a ref beginning with '--' was passed straight into the argv; git parsed it
    as an option and rev-parse's output (the option's value, not a sha) was returned."""
    _init_repo(tmp_path)
    assert web_git.review_rev_parse(str(tmp_path), "--exec-path=/tmp/evil") is None
    assert web_git.review_rev_parse(str(tmp_path), "--git-dir=/tmp/evil") is None


def test_review_rev_parse_unknown_ref_is_none(tmp_path):
    _init_repo(tmp_path)
    assert web_git.review_rev_parse(str(tmp_path), "refs/heads/does-not-exist") is None

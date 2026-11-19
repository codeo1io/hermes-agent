"""Release-adoption escape regression (fork patch, item-392 class).

Both-ways pin: the escape must fire for a PR head that carries a vX.Y.Z
release tag the base lacks, and must NOT fire for an ordinary PR. The
`git tag --merged`-based port was runner-sensitive (PR #578: empty listing
under partial clone) — this test drives the REAL git plumbing against a
synthetic GitHub-shaped PR merge ref (HEAD^1 = base, HEAD^2 = PR head),
annotated and lightweight tags both.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.ci import catalog_changed_entries as cce


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          cwd=repo, capture_output=True, text=True, check=check)


def _seed(repo: Path) -> None:
    _git(repo, "init", "-q", "-b", "main")
    (repo / "f.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")


def _pr_merge_ref(repo: Path, base: str, head: str) -> None:
    """Check out the GitHub-style pull_request merge commit (base merged into head)."""
    _git(repo, "checkout", "-q", "--detach", head)
    _git(repo, "merge", "--no-ff", "--no-edit", base)


class TestAdoptionEscape:
    def test_annotated_release_tag_on_head_fires(self, tmp_path: Path, monkeypatch) -> None:
        repo = tmp_path / "r"
        repo.mkdir()
        _seed(repo)
        # release line: tag v9.9.9 on a child commit
        _git(repo, "checkout", "-q", "-b", "release")
        (repo / "release.txt").write_text("release\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "release work")
        _git(repo, "tag", "-a", "v9.9.9", "-m", "release")  # annotated
        release_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        # main advances independently (no v9.9.9)
        _git(repo, "checkout", "-q", "main")
        (repo / "main.txt").write_text("main\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "main work")
        base_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        # PR merge ref: head^1 = base(main), head^2 = release branch
        # PR merge ref in GitHub's parent order: HEAD^1 = base(main), HEAD^2 =
        # PR head (live shape on pull/578/merge: 'Merge <head> into <base>',
        # base is parent[0]) — create the merge from the BASE side.
        _git(repo, "checkout", "-q", "--detach", base_sha)
        _git(repo, "merge", "--no-ff", "--no-edit", release_sha)
        monkeypatch.chdir(repo)  # the gate reads the process cwd (CI: step cwd = workspace)
        assert cce._release_adoption_tag() == "v9.9.9"

    def test_lightweight_release_tag_fires(self, tmp_path: Path, monkeypatch) -> None:
        repo = tmp_path / "r"
        repo.mkdir()
        _seed(repo)
        _git(repo, "checkout", "-q", "-b", "release")
        (repo / "release.txt").write_text("release\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "release work")
        _git(repo, "tag", "v8.8.8")  # lightweight: ref points straight at commit
        release_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _git(repo, "checkout", "-q", "main")
        (repo / "main.txt").write_text("main\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "main work")
        base_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        # PR merge ref in GitHub's parent order: HEAD^1 = base(main), HEAD^2 =
        # PR head (live shape on pull/578/merge: 'Merge <head> into <base>',
        # base is parent[0]) — create the merge from the BASE side.
        _git(repo, "checkout", "-q", "--detach", base_sha)
        _git(repo, "merge", "--no-ff", "--no-edit", release_sha)
        monkeypatch.chdir(repo)  # the gate reads the process cwd (CI: step cwd = workspace)
        assert cce._release_adoption_tag() == "v8.8.8"

    def test_ordinary_pr_no_release_tag_does_not_fire(self, tmp_path: Path, monkeypatch) -> None:
        repo = tmp_path / "r"
        repo.mkdir()
        _seed(repo)
        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "g.txt").write_text("feature\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "feature work")
        _git(repo, "tag", "nightly-20261110")  # non-release shape: must not fire
        head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _git(repo, "checkout", "-q", "main")
        base_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _git(repo, "checkout", "-q", "--detach", base_sha)
        _git(repo, "merge", "--no-ff", "--no-edit", head_sha)
        monkeypatch.chdir(repo)  # the gate reads the process cwd (CI: step cwd = workspace)
        assert cce._release_adoption_tag() is None

    def test_tag_reachable_from_both_sides_does_not_fire(self, tmp_path: Path, monkeypatch) -> None:
        # A release tag the BASE already carries is not an adoption.
        repo = tmp_path / "r"
        repo.mkdir()
        _seed(repo)
        _git(repo, "tag", "v1.0.0")
        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "g.txt").write_text("feature\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "feature work")
        head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _git(repo, "checkout", "-q", "main")
        base_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _git(repo, "checkout", "-q", "--detach", base_sha)
        _git(repo, "merge", "--no-ff", "--no-edit", head_sha)
        monkeypatch.chdir(repo)  # the gate reads the process cwd (CI: step cwd = workspace)
        assert cce._release_adoption_tag() is None

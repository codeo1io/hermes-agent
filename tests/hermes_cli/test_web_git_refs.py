"""Option-looking refs must never reach git's option parser (rm-045c / assess C10).

``GET /api/git/review/rev-parse?ref=`` feeds a dashboard-supplied string straight
into a ``git rev-parse`` argv. Unchecked, an option-looking "ref" is consumed by
git's own option parser instead of being resolved as a revision: on the fleet git
(2.34.1) ``--show-toplevel`` makes rev-parse print the server's absolute repo
path and ``--version`` is echoed verbatim — a server-path leak and a garbage
"sha" delivered to the dashboard. A git ref name can never start with ``-``, so
the behavior contract is: a leading-dash ref resolves to nothing, and real refs
keep resolving exactly as before.
"""

import subprocess

import pytest

from hermes_cli import web_git


def _git(repo, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo),
         "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        check=True, capture_output=True,
    )


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)],
                   check=True, capture_output=True)
    (repo / "f.txt").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


@pytest.mark.parametrize("ref", ["--version", "--show-toplevel", "--absolute-git-dir"])
def test_review_rev_parse_rejects_option_looking_refs(git_repo, ref):
    assert web_git.review_rev_parse(str(git_repo), ref) is None


def test_ref_exists_rejects_option_looking_refs(git_repo):
    # Same class, same rule for the existence probe (defensive: under
    # ``--verify --quiet`` this git exits non-zero anyway — pin the contract).
    assert web_git._ref_exists(str(git_repo), "--show-toplevel") is False
    assert web_git._ref_exists(str(git_repo), "--version") is False


def test_real_refs_still_resolve(git_repo):
    head = subprocess.run(
        ["git", "-C", str(git_repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert web_git._ref_exists(str(git_repo), "refs/heads/main") is True
    assert web_git._ref_exists(str(git_repo), "no-such-ref") is False
    assert web_git.review_rev_parse(str(git_repo), "HEAD") == head
    assert web_git.review_rev_parse(str(git_repo), None) == head
    assert web_git.review_rev_parse(str(git_repo), "no-such-ref") is None

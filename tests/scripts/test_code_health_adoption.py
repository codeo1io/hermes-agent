"""Release-adoption provenance: the ratchet judges what an adoption merge itself changed.

Fixture: a tiny repo whose "main" carries the engine, a fork-era module, and a
tagged "upstream release" branch with its own pre-existing violation. The
adoption merge brings the release verbatim; the assertions pin the contract:

- a finding on a file byte-identical to the release blob is demoted to
  advisory (upstream's debt, adopted as-is -- never blocks the adoption),
- the same rule on a file the merge edited (conflict resolution) stays
  blocking (the merge owns what it touched),
- an ordinary two-parent merge without a new release tag demotes nothing,
- single-parent commits are never adoption merges.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from scripts.code_health.adoption import adoption_parent, demote_adopted
from scripts.code_health.model import Finding

REPO = Path(__file__).resolve().parents[2]

# One blocking-pattern violation, written so the AST rule fires on it.
_SWALLOW = "def swallow():\n    try:\n        pass\n    except Exception:\n        pass\n"


def _env() -> dict[str, str]:
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=__import__("os").devnull, GIT_CONFIG_NOSYSTEM="1")
    return env


def _sh(cwd: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), cwd=cwd, env=_env(), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                          timeout=600, check=False)


def _git(repo: Path, *args: str) -> str:
    proc = _sh(repo, "git", *args)
    assert proc.returncode == 0, (args, proc.stdout, proc.stderr)
    return proc.stdout.strip()


def _write(repo: Path, files: Mapping[str, str]) -> None:
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _commit(repo: Path, files: Mapping[str, str], message: str) -> str:
    _write(repo, files)
    _git(repo, "add", "--all", "--", *files)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp_path: Path) -> tuple[Path, str]:
    """main with the engine, a violating fork module, and the v1.0.0 release tag."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "scripts/code_health").mkdir(parents=True)
    shutil.copy2(REPO / "scripts/code_health/adoption.py", repo / "scripts/code_health/adoption.py")
    (repo / "scripts/code_health/__init__.py").write_text("", encoding="utf-8")
    base = _commit(repo, {"pkg/fork_module.py": _SWALLOW}, "fork base")
    # The "upstream release": the same violating module, verbatim, tagged v1.0.0.
    _git(repo, "branch", "upstream", "HEAD")
    _git(repo, "checkout", "-q", "upstream")
    release = _commit(repo, {"pkg/upstream_only.py": _SWALLOW}, "release adds upstream_only")
    _git(repo, "tag", "v1.0.0")
    _git(repo, "checkout", "-q", "main")
    assert base == _git(repo, "rev-parse", "HEAD")
    return repo, release


def _finding(path: str) -> Finding:
    return Finding(path=path, rule="BLE001", scope="swallow", line=4,
                   detail="blind `except Exception`", blocking=True)


def test_adoption_merge_demotes_only_release_identical_files(tmp_path):
    repo, release = _repo(tmp_path)
    # The adoption merge: main gets upstream_only.py verbatim; fork_module.py
    # is edited (a conflict resolution would look the same to blob identity).
    _write(repo, {"pkg/upstream_only.py": _SWALLOW,
                  "pkg/fork_module.py": _SWALLOW + "\ndef extra():\n    return 2\n"})
    _git(repo, "add", "--all")
    tree = _git(repo, "write-tree")
    commit = _sh(repo, "git", "commit-tree", tree, "-p", "main", "-p", release,
                 "-m", "merge: adopt v1.0.0")
    assert commit.returncode == 0
    head = commit.stdout.strip()
    assert adoption_parent(repo, head) == release

    findings = [_finding("pkg/upstream_only.py"), _finding("pkg/fork_module.py")]
    demoted = demote_adopted(findings, repo, head, release)
    assert demoted == 1
    by_path = {f.path: f for f in findings}
    assert by_path["pkg/upstream_only.py"].blocking is False
    assert "byte-identical" in by_path["pkg/upstream_only.py"].detail
    assert by_path["pkg/fork_module.py"].blocking is True


def test_ordinary_merge_and_single_parent_never_demote(tmp_path):
    repo, _release = _repo(tmp_path)
    # main already carries v1.0.0 (the release was adopted earlier): a later
    # two-parent merge (the PR-merge shape) brings no release tag new to main,
    # so nothing may demote.
    _git(repo, "merge", "-q", "--ff-only", "v1.0.0")
    _git(repo, "checkout", "-q", "-b", "feature", "HEAD~0")
    _commit(repo, {"pkg/feature.py": "def feature():\n    return 3\n"}, "feature work")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge the PR", "feature")
    head = _git(repo, "rev-parse", "HEAD")
    assert adoption_parent(repo, head) is None
    findings = [_finding("pkg/fork_module.py")]
    assert demote_adopted(findings, repo, head, adoption_parent(repo, head)) == 0
    assert findings[0].blocking is True
    # A single-parent commit is never an adoption merge, even on a tagged line.
    plain = _commit(repo, {"pkg/another.py": _SWALLOW}, "plain commit")
    assert adoption_parent(repo, plain) is None


def test_detection_is_insensitive_to_titles(tmp_path):
    repo, _release = _repo(tmp_path)
    # A merge titled like an adoption but without a new release tag: no demotion.
    _sh(repo, "git", "merge", "--no-ff", "--no-commit", "-m", "x", "v1.0.0")
    tree = _git(repo, "write-tree")
    fake = _sh(repo, "git", "commit-tree", tree, "-p", "main", "-p", "main",
               "-m", "merge: adopt upstream v9.9.9 (fake)")
    head = fake.stdout.strip()
    # Second parent is main itself: no tag new to main, so not an adoption.
    assert adoption_parent(repo, head) is None
    findings = [_finding("pkg/fork_module.py")]
    demote_adopted(findings, repo, head, adoption_parent(repo, head))
    assert findings[0].blocking is True
    assert sys.modules["scripts.code_health.adoption"] is not None


def test_ci_shape_supplies_head_commit_provenance(tmp_path, monkeypatch):
    """CI passes ``--base`` with no ``--head`` (lint.yml: ``--base HEAD^1``): the judged
    artifact is the working tree, whose provenance commit is HEAD itself. Without
    ``head_commit`` the demotion path saw a tree/None head and could never fire —
    the exact seam the first full run missed (0 demotions at the adoption merge)."""
    from scripts.code_health import adoption, cli, gitio

    repo, release = _repo(tmp_path)
    # The adoption merge at HEAD: main adopts upstream_only.py verbatim.
    _write(repo, {"pkg/upstream_only.py": _SWALLOW,
                  "pkg/fork_module.py": _SWALLOW + "\ndef extra():\n    return 2\n"})
    _git(repo, "add", "--all")
    tree = _git(repo, "write-tree")
    commit = _sh(repo, "git", "commit-tree", tree, "-p", "main", "-p", release,
                 "-m", "merge: adopt v1.0.0")
    assert commit.returncode == 0
    head_sha = commit.stdout.strip()
    # HEAD on its own branch so `main` stays the pre-adoption base.
    _git(repo, "branch", "-f", "adoption", head_sha)
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/adoption")
    monkeypatch.chdir(repo)  # cli.main resolves the repo from the cwd

    class _StubMeasurer:
        def __init__(self, repo_, ruff, known_env=None): pass
        def measure(self, rev, paths): return {}

    change = __import__("types").SimpleNamespace(new="pkg/upstream_only.py", old=None)
    seen: dict[str, str | None] = {}
    monkeypatch.setattr(cli, "Measurer", _StubMeasurer)
    monkeypatch.setattr(cli, "resolve_ruff", lambda repo_: [])
    monkeypatch.setattr(cli, "compare", lambda *a, **k: [])
    monkeypatch.setattr(cli, "apply_allows", lambda *a, **k: None)
    monkeypatch.setattr(gitio, "changed_files", lambda repo_, base, head: [change])
    monkeypatch.setattr(gitio, "known_env_names", lambda repo_, rev: [])
    monkeypatch.setattr(adoption, "adoption_parent",
                        lambda repo_, head: seen.setdefault("head", head))
    calls: dict[str, dict] = {}
    real_run = cli.run

    def spy(repo_, base_, head_, **kwargs):
        calls["run"] = kwargs
        return real_run(repo_, base_, head_, **kwargs)

    monkeypatch.setattr(cli, "run", spy)
    rc = cli.main(["--base", "main"])
    assert rc == 0
    # The demotion path received the HEAD commit (an adoption merge), not None.
    assert seen["head"] == head_sha
    assert calls["run"]["head_commit"] == head_sha

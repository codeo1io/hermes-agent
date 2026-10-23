"""Release-adoption provenance for the ratchet.

An adoption merge (a merge commit that brings an upstream release tag main has
not seen) brings upstream's whole tree. The per-unit ratchet is keyed to
ordinary PRs -- where every file new to main is fork-written and its violations
are the PR's own debt. On an adoption, that rule fires on upstream's
pre-existing violations instead: files the merge took from upstream unchanged
carry findings upstream's own reviewers already weighed (31
``# health: allow`` waivers came across in v0.22.4 alone).

The rule here mirrors the plugin-catalog gate's adoption detection: when the
judged head is a two-parent merge whose second parent carries a vX.Y.Z release
tag that the first parent (main) does not yet have, a finding on a file whose
head blob is byte-identical to the release commit's blob is demoted to
advisory -- the merge adopted that code as-is, and the fork's bar is what the
merge ITSELF changed. A file resolved in a conflict, edited by a sweep, or
added by the branch differs from the release blob, and every finding on it
stays fully blocking, so an adoption cannot smuggle in violations of its own.

Ordinary PRs are unaffected: GitHub's PR merge commit has a feature branch as
its second parent, and a feature branch carries a new release tag only when it
actually adopts one; every finding then keeps its blocking weight.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.code_health.model import Finding

_RELEASE = re.compile(r"^v([0-9]+)\.([0-9]+)\.([0-9]+)$")


def adoption_parent(repo: Path, head: str | None) -> str | None:
    """The release commit ``head`` adopts, when ``head`` is an adoption merge, else None.

    Shape check (structural, never title matching): ``head`` is a commit with
    exactly two parents, and a vX.Y.Z tag reachable from the second parent is
    missing from the first parent's history -- main has not adopted that
    release. The newest such tag's peeled commit is returned as the provenance
    root for blob comparison.
    """
    if head is None:
        return None
    subject = _git(repo, "cat-file", "commit", head, check=False)
    if not subject:
        return None  # a tree-ish head (index tree) has no parents to judge
    parents = [line.split()[1] for line in subject.splitlines()
               if line.startswith("parent ")]
    if len(parents) != 2:
        return None
    first, second = parents
    in_first = set(_git(repo, "tag", "--merged", first).splitlines())
    in_second = set(_git(repo, "tag", "--merged", second).splitlines())
    new_tags = [t for t in in_second - in_first if _RELEASE.match(t)]
    if not new_tags:
        return None

    def _ver(tag: str) -> tuple[int, int, int]:
        m = _RELEASE.match(tag)
        assert m is not None
        return tuple(int(x) for x in m.groups())  # type: ignore[return-value]

    newest = max(new_tags, key=_ver)
    return _git(repo, "rev-parse", f"{newest}^{{commit}}")


def demote_adopted(findings: list[Finding], repo: Path, head: str | None,
                   parent: str | None) -> int:
    """Demote findings on files byte-identical to the adoption parent to advisory.

    Blob-identity decides provenance per file: a head blob equal to the release
    commit's blob for the same path means the merge did not alter that file, so
    its findings are upstream's pre-existing debt, not this merge's. Edited
    files (conflict resolutions, sweep commits, branch work) differ and stay
    blocking. Returns the number of findings demoted.
    """
    if parent is None or head is None or not findings:
        return 0
    adopted: set[str] = set()
    for path in sorted({f.path for f in findings}):
        head_blob = _git(repo, "rev-parse", f"{head}:{path}", check=False) if head else ""
        parent_blob = _git(repo, "rev-parse", f"{parent}:{path}", check=False)
        if head_blob and head_blob == parent_blob:
            adopted.add(path)
    demoted = 0
    for finding in findings:
        if finding.path in adopted and finding.allowed_reason is None:
            finding.blocking = False
            finding.detail += (
                "  [advisory: file is byte-identical to the adopted release blob; "
                "upstream's pre-existing finding, adopted as-is]")
            demoted += 1
    return demoted


def _git(repo: Path, *args: str, check: bool = True) -> str:
    import subprocess
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          stdin=subprocess.DEVNULL, timeout=60, check=False)
    if check and proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace')}")
    return proc.stdout.decode(errors="replace").strip()

#!/usr/bin/env python3
"""List the catalog entry files a plugin-catalog PR adds or changes, for the pinned-source gate.

Runs on the ``pull_request`` merge commit: HEAD diffed against its first parent is exactly what
the PR would land. Anything else is refused rather than silently diffing a single commit.

Admission PRs must be data-only: the gate's own enforcement code (the workflow, the validator,
the composite actions, the built hermes) resolves from the PR checkout, so an entry PR that also
touches tooling could neuter the gate vetting it. Contributor email maps are data the gate never
executes; README/policy/CI PRs with no entry change skip this check.

Writes ``files`` (newline-separated entry paths, empty when none) to ``$GITHUB_OUTPUT``.
Exit 0 = listed, 1 = not a merge commit or a non-data path in an entry PR, other = git failed.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

_REMOVED_LIST = re.compile(r"/removed\.yaml$")
_RELEASE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
_DATA_PATHS = re.compile(r"^(plugin-catalog|contributors/emails)/")


_GIT_SECONDS = 900


def _git_lines(*args: str) -> list[str]:
    # git quotes unusual path bytes itself (core.quotePath), so its output is ASCII.
    out = subprocess.run(["git", *args], stdout=subprocess.PIPE, encoding="utf-8", check=True,
                         timeout=_GIT_SECONDS).stdout
    return out.rstrip("\n").split("\n") if out.strip("\n") else []


def changed_entries() -> list[str]:
    # Added + modified + renamed + typechanged entry files only; deletions and removed.yaml have
    # nothing to clone. A rename or file->symlink change that slipped past this list would skip
    # the supply-chain gate.
    changed = _git_lines("diff", "--name-only", "--diff-filter=AMRT", "HEAD^1", "HEAD",
                         "--", "plugin-catalog/*.yaml", "plugin-catalog/*.yml")
    return [path for path in changed if not _REMOVED_LIST.search(path)]


def non_data_paths() -> list[str]:
    return [path for path in _git_lines("diff", "--name-only", "HEAD^1", "HEAD")
            if not _DATA_PATHS.search(path)]


def _is_ancestor(commit: str, rev: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", commit, rev],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          check=False, timeout=_GIT_SECONDS).returncode == 0


def _release_adoption_tag() -> str | None:
    # fork patch (item-392 class, v0.23.0/v0.22.x adoption lanes): the PR head
    # carries a vX.Y.Z release tag that main does not have yet (a merge of an
    # upstream release). The entry files it brings were admitted by UPSTREAM's
    # own copy of this gate at their source tags — re-cloning and re-validating
    # hundreds of pinned entries here cannot out-vet that, and the data-only
    # rule below structurally cannot hold for a whole-tree merge. Detection is
    # exact (tag ancestry), not title matching: any ordinary entry PR still
    # runs the full gate. Probed per tag with merge-base --is-ancestor on the
    # peeled commit — `git tag --merged` listing proved runner-sensitive
    # (PR #578: empty set under partial-clone filter, escape silently dead).
    out = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short) %(objectname) %(*objectname)",
         "refs/tags"], stdout=subprocess.PIPE, encoding="utf-8", check=False,
        timeout=_GIT_SECONDS).stdout
    for line in out.splitlines():
        name, tag_obj, peeled = (line.split() + ["", ""])[:3]
        if not _RELEASE_TAG.fullmatch(name):
            continue
        commit = peeled or tag_obj  # lightweight tags point straight at the commit
        if _is_ancestor(commit, "HEAD^2") and not _is_ancestor(commit, "HEAD^1"):
            return name
    return None


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="List the catalog entries a PR changes.").parse_args(argv)
    merge = subprocess.run(["git", "rev-parse", "-q", "--verify", "HEAD^2"],
                           stdout=subprocess.DEVNULL, check=False, timeout=_GIT_SECONDS)
    if merge.returncode != 0:
        print("::error::expected the pull_request merge commit as HEAD")
        return 1
    adopt_tag = _release_adoption_tag()
    if adopt_tag:
        print(f"::notice::release adoption detected (brings tag {adopt_tag}): "
              "skipping pinned-source re-validation of upstream-admitted entries")
    try:
        changed = changed_entries() if not adopt_tag else []
        outside = non_data_paths() if changed else []
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    if outside:
        print("::error::catalog entry PRs may only touch plugin-catalog/** and "
              "contributors/emails/**, found:")
        # Filenames are PR-controlled; a newline in one could smuggle a workflow command into
        # the log.
        print(" ".join(outside))
        return 1

    listed = "\n".join(changed)
    print("Changed catalog entries:")
    print(listed or "<none>", flush=True)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8", newline="\n") as output:
        output.write(f"files<<__EOF__\n{listed}\n__EOF__\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

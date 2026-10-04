"""I54 invariant: nothing the OSV scan executes is left unpinned.

The original I54 form (run d09f0dd2, commit 43e48f773b) verified a curl'd
osv-scanner binary against the release SHA256SUMS before exec, because the
workflow inlined the install on the self-hosted pool. Main superseded that
mechanism: the scan now delegates to Google's official reusable workflow
pinned by full commit SHA, and no binary is downloaded by this repo at all.
The invariant survives the mechanism change unchanged in meaning — every
action ref the workflow executes is a full-SHA pin with an auditable version
comment, and no step fetches a remote executable to run it. Regression guard
for the repo SHA-pinning policy (#9801 / roadmap I54).

Lives under tests/ci/ with the other workflow-reading tests (e.g.
test_classify_changes.py reads .github/workflows/ci.yaml); root tests/ is
reserved for root-level modules.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/osv-scanner.yml"

# `uses:` at job or step level, optionally followed by a `# vX.Y.Z` comment.
_USES_LINE = re.compile(
    r"^[ \t]*uses:[ \t]*(?P<ref>\S+)(?:[ \t]+#[ \t]*(?P<version>v\d+\.\d+\.\d+))?[ \t]*$",
    re.MULTILINE,
)


def test_every_action_ref_is_a_full_sha_pin_with_version_comment() -> None:
    refs = [(m.group("ref"), m.group("version")) for m in _USES_LINE.finditer(WORKFLOW.read_text())]
    assert refs, "osv-scanner.yml must reference at least one action"
    for ref, version in refs:
        action, _, commit = ref.rpartition("@")
        assert re.fullmatch(r"[0-9a-f]{40}", commit), (
            f"{action} must be pinned by a full 40-hex commit SHA, got {commit!r}"
        )
        assert version is not None, (
            f"{action}@{commit} must carry a `# vX.Y.Z` comment so the pin is auditable"
        )


def test_scan_delegates_to_a_pinned_workflow_and_downloads_nothing_itself() -> None:
    doc = yaml.safe_load(WORKFLOW.read_text())
    scan = doc["jobs"]["scan"]
    assert "uses" in scan, (
        "the scan must delegate to a reusable workflow; an inlined scan reopens the "
        "unverified-executable class I54 closed"
    )
    assert scan["uses"].startswith("google/osv-scanner-action/"), (
        "delegation target must be the official osv-scanner action, itself SHA-pinned"
    )
    for job in doc["jobs"].values():
        for step in job.get("steps") or []:
            script = step.get("run", "")
            assert not re.search(r"\b(?:curl|wget)\b", script), (
                "no inlined network fetch: an executable downloaded here runs without the "
                "digest verification the pinned reusable workflow provides (I54)"
            )

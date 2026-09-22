"""I54 invariant: the osv-scanner CI binary is verified before it executes.

The workflow inlines the osv-scanner install on the self-hosted pool (the
upstream reusable action lacked first-class v2 syntax support; f0f677187a),
so the workflow itself downloads and runs a release binary. That binary must
be pinned to an exact version + sha256, verified against the release
SHA256SUMS asset with a fail-closed comparison, BEFORE anything executes it.
Regression for the repo SHA-pinning policy (#9801 / roadmap I54).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/osv-scanner.yml"


def _install_step() -> dict:
    doc = yaml.safe_load(WORKFLOW.read_text())
    steps = doc["jobs"]["scan"]["steps"]
    for step in steps:
        if step.get("name") == "Install pinned osv-scanner":
            return step
    raise AssertionError("install step missing from osv-scanner workflow")


def test_install_step_pins_version_and_sha256_inline() -> None:
    script = _install_step()["run"]
    # Exact version pin (vX.Y.Z) and a 64-hex digest, both recorded inline so
    # a review sees exactly what runs on the self-hosted pool.
    assert re.search(r"\bVER=v\d+\.\d+\.\d+\b", script), (
        "exact osv-scanner version must be pinned inline"
    )
    assert re.search(r"\bSHA256=[0-9a-f]{64}\b", script), (
        "osv-scanner sha256 must be pinned inline"
    )


def test_binary_verified_against_release_sums_before_exec() -> None:
    script = _install_step()["run"]
    # The release SHA256SUMS asset is fetched and is the verification source.
    assert "osv-scanner_SHA256SUMS" in script, (
        "install must download the release SHA256SUMS asset"
    )
    # Published sums line is cross-checked against the pinned digest (fail
    # closed on empty/mismatch) and the binary digest is verified explicitly.
    assert re.search(r"\"\$published\"\s*!=\s*\"\$SHA256\"", script), (
        "published SHA256SUMS line must be compared to the pinned digest"
    )
    assert "sha256sum -c -" in script, "binary digest must be verified via sha256sum -c"
    assert "set -euo pipefail" in script, "install must run fail-closed"
    # Verification must precede ANY execution of the binary.
    first_exec = min(
        i for i in (script.find("chmod +x"), script.find("--version")) if i != -1
    )
    verify_idx = script.find("sha256sum -c -")
    assert verify_idx != -1 and verify_idx < first_exec, (
        "digest verification must run before the binary is executed"
    )

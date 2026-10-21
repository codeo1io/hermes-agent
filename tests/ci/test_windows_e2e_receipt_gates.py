"""Windows install-e2e receipt plumbing: the leg must end SUCCESSFUL once the
classifier accepts an install-phase failure.

The result chart (install-e2e.yml's report job -> generate-e2e-matrix.mjs)
renders ``known [n]`` ONLY for a successful job that uploaded a receipt
artifact; every failed job renders ❌. The windows leg workflow therefore has
to keep every step after the install phase green when the install phase
classifies: the update phase is skipped (``known_failure`` output set), and —
the regression this file pins — the post-update ``Verify install stamps``
step must skip too, because a classified install-phase failure means nothing
landed, so no install-stamp.json exists and stamp verification would fail the
otherwise-successful leg (adoption #501 brought the step gated only on the
update phase's output, which is empty when update is skipped).

The receipt stage/upload steps must additionally run under ``always()`` so a
later unrelated step failure cannot strand the receipt — same contract as the
macos leg workflow's receipt upload.

Here the REAL workflow file's ``if:`` gates are replayed through the REAL
expression evaluator (tests/ci/_gha_expr.py) for the four shapes a leg can
end in, so a gate that stops consuming ``steps.install.outputs`` fails here,
not three hours into a windows runner.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import hermes_yaml
from tests.ci import _gha_expr as gha

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/install-e2e-windows-run.yml"


@pytest.fixture(scope="module")
def steps() -> dict[str, dict]:
    doc = hermes_yaml.safe_load(WORKFLOW.read_text(encoding="utf-8-sig"))
    return {s.get("name", s.get("id", "")): s for s in doc["jobs"]["e2e"]["steps"]}


def gate(steps: dict[str, dict], name: str, ctx: dict) -> bool:
    """Evaluate the named step's ``if:`` under ctx, modelling step results.

    A step that ran and succeeded exposes its outputs; one that was skipped
    (its own gate false) exposes nothing — the shape verify-stamp misread.
    GitHub additionally prefixes every explicit ``if:`` that does not call
    ``always()``/``failure()``/``cancelled()`` with an implicit success()
    (an earlier failed step skips the step outright); that precondition is
    modelled here so the ``always()`` guards are actually pinned.
    """
    expr = steps[name].get("if")
    if (
        expr is not None
        and not re.search(r"\b(always|failure|cancelled)\s*\(", str(expr))
        and not ctx["__status__"]["success"]()
    ):
        return False
    return gha.condition(expr, ctx)


def _ctx(
    install: str, update_ran: bool, update_known: str = "", failure: bool = False
) -> dict:
    install_outputs = {"known_failure": install}
    update_outputs = {"known_failure": update_known} if update_ran else {}
    # Job status functions: always() is unconditionally true; failure() is
    # true when an earlier step failed (modelled: install outcome failure).
    status = {
        "always": lambda: True,
        "success": lambda: not failure,
        "failure": lambda: failure,
        "cancelled": lambda: False,
    }
    return {
        "steps": {
            "install": {
                "outputs": install_outputs,
                "outcome": "success" if not failure else "failure",
            },
            "update": {"outputs": update_outputs, "outcome": "success"},
        },
        "__status__": status,
    }


SCENARIOS = {
    # install classified -> update SKIPPED (its outputs dict stays empty)
    "install_classified": _ctx(
        "pre-pm-june-desktop-renderer-layout", update_ran=False, failure=False
    ),
    # update classified -> install green, update output set
    "update_classified": _ctx(
        "", update_ran=True, update_known="pre-pm-june-desktop-renderer-layout"
    ),
    # clean pass
    "clean_pass": _ctx("", update_ran=True),
    # install failed unclassified (rethrow) -> job already red
    "install_failed_unclassified": _ctx("", update_ran=False, failure=True),
}


def test_verify_stamp_skips_when_install_classified(steps):
    # THE regression: install classified, update skipped -> stamp verification
    # must not run against a tree that legitimately has no install-stamp.json.
    assert not gate(
        steps,
        "Verify install stamps describe the updated checkout",
        SCENARIOS["install_classified"],
    )


def test_verify_stamp_skips_when_update_classified(steps):
    assert not gate(
        steps,
        "Verify install stamps describe the updated checkout",
        SCENARIOS["update_classified"],
    )


def test_verify_stamp_runs_on_clean_pass(steps):
    assert gate(
        steps,
        "Verify install stamps describe the updated checkout",
        SCENARIOS["clean_pass"],
    )


def test_update_phase_gates_on_install_classification(steps):
    # Pre-existing contract (restored by fix-queue 339 / PR #509): a
    # classified install failure skips the update phase entirely.
    update = next(
        s for s in steps.values() if str(s.get("name", "")).startswith("Update ")
    )
    assert not gha.condition(update.get("if"), SCENARIOS["install_classified"])
    assert gha.condition(update.get("if"), SCENARIOS["clean_pass"])


def test_receipt_steps_run_after_a_later_failure(steps):
    # The receipt stage/upload steps carry always(): a later step's failure
    # (pre-fix: verify-stamp) must not skip them, or the chart cannot render
    # known [n] and the leg's story is lost. Modelled with a failed install
    # step outcome; always() must still admit the receipt uploads.
    ctx = _ctx("pre-pm-june-desktop-renderer-layout", update_ran=False, failure=True)
    assert gate(steps, "Stage known-failure receipt", ctx)
    assert gate(steps, "Upload known-failure receipt", ctx)
    # And when nothing classified, no receipt is staged at all.
    assert not gate(steps, "Stage known-failure receipt", SCENARIOS["clean_pass"])
    assert not gate(steps, "Upload known-failure receipt", SCENARIOS["clean_pass"])

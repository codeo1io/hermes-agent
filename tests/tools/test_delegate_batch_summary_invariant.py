"""Behavior contracts for the delegation batch-summary false-failure guard (rm-032).

Regression class: upstream #129450 — batch tasks reported failed while passing because
*prose* in a task's output (someone writing the word "error") was mistaken for the task's
status. Our ``delegate_tool_results`` surface pins two halves of that invariant:

* the preview classifier (:func:`_looks_like_error_output`) flags only structured failure
  markers — narrative text never paints a task red; and
* the lifecycle hook (:func:`_fire_subagent_stop_hooks`) carries the structured ``status``
  field verbatim, so downstream consumers can never re-derive failure from prose.

Together: failure is a data field, never a re-derivation from narrative.
"""

from types import SimpleNamespace

import pytest

from tools.delegate_tool_results import _fire_subagent_stop_hooks, _looks_like_error_output


# ---------------------------------------------------------------------------
# _looks_like_error_output: content-classifier contract
# ---------------------------------------------------------------------------

CALM_OUTPUTS = [
    "def f():\n    return 1\n",
    "All 4 steps completed; artifact written.",
    "",  # empty output is not an error
    "DEF RETURN: none\n",  # uppercase word boundaries must not match
]

SCARY_BUT_FINE = [
    # The word "error" narrating someone ELSE'S environment, not a failure.
    "Suppressed a harmless ValueError from the linter; run continued.",
    # stderr chatter that is progress, not failure.
    "note: warnings emitted while compiling stdlib",
    "I will fix the error handling next; for now the test passes.",
]

REAL_ERRORS = [
    # Classic first-line markers.
    "Traceback (most recent call last):\n  File ...\nValueError: boom",
    "ERROR: could not build wheel for foo",
    "Failed: 2 tests failed",
    # Structured JSON: an `error` key, or an error/failed `status`.
    '{"error": "connection refused while fetching model list"}',
    '{"status": "failed", "retries": 3}',
]


@pytest.mark.parametrize("text", CALM_OUTPUTS + SCARY_BUT_FINE)
def test_narrative_text_is_not_an_error(text):
    assert _looks_like_error_output(text) is False


@pytest.mark.parametrize("text", REAL_ERRORS)
def test_structured_failure_markers_are_errors(text):
    assert _looks_like_error_output(text) is True


def test_classifier_is_first_line_anchored():
    # Deliberate conservatism: a traceback buried mid-output is narrative context, not a
    # status. Only the FIRST line's classic markers decide (see the function docstring).
    assert _looks_like_error_output("progress...\n" + REAL_ERRORS[0]) is False


def test_contract_catches_the_naive_substring_classifier():
    """Red-on-injection proof for the #129450 class.

    Swap the classifier for the naive ``"error" in text`` version that upstream shipped,
    and this contract goes red: every SCARY_BUT_FINE case is a false positive of the naive
    implementation while the real classifier must reject all of them.
    """
    naive = lambda text: "error" in str(text).lower()  # noqa: E731 - the upstream bug, inlined
    bug_false_positives = [t for t in SCARY_BUT_FINE if naive(t)]
    assert bug_false_positives, "SCARY_BUT_FINE must contain the naive-bug false positives"
    for text in bug_false_positives:
        assert _looks_like_error_output(text) is False


# ---------------------------------------------------------------------------
# _fire_subagent_stop_hooks: structured status is authoritative
# ---------------------------------------------------------------------------

def _entry(status: str, preview: str) -> dict:
    # A child result whose *narrative* is full of failure words while its structured
    # status is fine — the #129450 shape. `task_index` is the child-lookup key.
    return {
        "task_index": 0,
        "status": status,
        "summary": preview,
        "output": preview,
        "duration_seconds": 1.5,
    }


@pytest.fixture
def captured_hooks(monkeypatch):
    captured: list[dict] = []
    # Production late-imports invoke_hook from hermes_cli.plugins inside the function
    # (facade/sibling rule), so that module is the patch target that bites.
    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda hook_name, **payload: captured.append({"hook": hook_name, **payload}),
    )
    return captured


def test_stop_hook_carries_structured_status_verbatim(captured_hooks):
    results = [_entry("completed", "Traceback narration: I handled the ValueError error")]
    child = SimpleNamespace(session_id="child-1")
    parent = SimpleNamespace(session_id="sess-1", _current_turn_id="turn-1")

    _fire_subagent_stop_hooks(results, {0: child}, parent)

    assert captured_hooks and captured_hooks[0]["hook"] == "subagent_stop"
    payload = captured_hooks[0]
    # The hook sees the structured status even though the summary reads like a failure —
    # consumers must never re-derive failure from prose.
    assert payload["child_status"] == "completed"
    assert payload["child_session_id"] == "child-1"
    assert payload["child_summary"].startswith("Traceback narration")


def test_stop_hook_status_follows_child_not_summary(captured_hooks):
    # Summary says success; structured status says interrupted. Structured wins.
    results = [_entry("interrupted", "everything worked great")]
    child = SimpleNamespace(session_id="child-2")
    parent = SimpleNamespace(session_id="sess-2", _current_turn_id="turn-2")

    _fire_subagent_stop_hooks(results, {0: child}, parent)

    assert captured_hooks[0]["child_status"] == "interrupted"


def test_cost_reduction_equals_sum_of_per_task_costs(captured_hooks):
    # The batch's cost verdict is exactly the reduction of per-task costs, and the
    # model-hidden cost/role fields are consumed (popped), never forwarded to hooks.
    entries = [
        {**_entry("completed", "a"), "_child_cost_usd": 0.5, "_child_role": "researcher"},
        {**_entry("completed", "b"), "_child_cost_usd": 1.25},
        {**_entry("failed", "c")},  # no cost recorded -> contributes 0
    ]
    total = _fire_subagent_stop_hooks(entries, {}, SimpleNamespace(session_id="s"))

    assert total == pytest.approx(1.75)
    for payload in captured_hooks:
        assert "child_cost" not in payload and "_child_cost_usd" not in payload
        assert "child_role" in payload  # forwarded as its own field, not the raw hidden key
    assert all("_child_cost_usd" not in e and "_child_role" not in e for e in entries)

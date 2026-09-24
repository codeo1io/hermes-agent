"""A parent interrupt must not wedge the batch on the executor join.

``_run_children_parallel`` polls futures with a short timeout precisely so a wedged
child cannot block the parent after an interrupt; the interrupt path reports the
still-pending children ``interrupted`` and abandons them. The ``with`` block's
exit join would still block on exactly those abandoned children — this test pins
the abandonment contract: interrupt returns bounded, with fabricated entries.
Regression for upstream #116435."""

import threading
import time
from types import SimpleNamespace

from tools.delegate_tool_dispatch import _Batch, _run_children_parallel


def _wedge_batch(parent_agent, wedge: threading.Event, n_children: int = 2) -> _Batch:
    """A faithful _Batch whose children block on ``wedge`` forever."""

    def _wedged_run_child(i, task, child):  # pragma: no cover - never returns within the test
        wedge.wait()
        return {"task_index": i, "status": "completed", "summary": None, "error": None}

    children = [(i, {"goal": f"task {i}"}, SimpleNamespace(_delegate_role="review")) for i in range(n_children)]
    batch = _Batch(
        task_list=[{"goal": f"task {i}"} for i in range(n_children)],
        children=children,
        parent_agent=parent_agent,
        creds={},
        context=None,
        top_role=None,
        max_children=n_children,
        live_deleg_id=None,
        live_writers=[None] * n_children,
        live_paths=[None] * n_children,
        origin_wake_sid="",
        origin_ui_session_id="",
        origin_owner_transport=None,
        origin_owner_session_record=None,
        origin_session_history_delivery=False,
        overall_start=time.monotonic(),
    )
    batch.run_child = _wedged_run_child  # instance attr shadows the real runner
    return batch


def test_interrupt_returns_bounded_with_wedged_children():
    """Interrupt with wedged children must return (not hang on the with-exit join)
    and report every child ``interrupted``."""
    wedge = threading.Event()
    parent_agent = SimpleNamespace(_interrupt_requested=False, _delegate_spinner=None)
    batch = _wedge_batch(parent_agent, wedge)
    results: list = []

    def _interrupt_soon() -> None:
        time.sleep(0.3)
        parent_agent._interrupt_requested = True

    timer = threading.Timer(0.3, _interrupt_soon)
    timer.daemon = True
    timer.start()

    runner = threading.Thread(
        target=_run_children_parallel, args=(batch, results), kwargs={"honor_parent_interrupt": True}, daemon=True
    )
    runner.start()
    runner.join(timeout=5.0)
    try:
        assert not runner.is_alive(), (
            "_run_children_parallel did not return within 5s of the interrupt — "
            "the executor join is blocking on the abandoned (wedged) children"
        )
        assert len(results) == 2
        assert all(entry["status"] == "interrupted" for entry in results), results
        assert {entry["task_index"] for entry in results} == {0, 1}
    finally:
        wedge.set()  # release wedged children even when the contract is violated (base code)
        timer.cancel()
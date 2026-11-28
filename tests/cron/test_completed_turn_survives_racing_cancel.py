"""A completed turn's result must survive a cancel signal that raced it.

2026-11-28 defect specimen (execution 72b2fef174f5477394e2218509e91272): the firer-side
watchdog polls the run's future in 5s slices. When the future completed but a cancel event
latched between polls (in the incident: a spurious claim-loss the unfenced mark caused), the
``done`` branch still called ``_abort_if_fire_claim_lost()`` first — so a turn that HAD
finished was interrupted-after-the-fact, its completed result discarded, and the run booked as
a retryable 'stopped' failure. The store-level fence is the authority on ownership; a cancel
that arrives after completion cannot change the outcome, so the completed result must win.
"""
import threading
from concurrent.futures import Future
from unittest.mock import MagicMock, patch


def test_completed_future_survives_a_racing_cancel():
    from cron.scheduler import _run_agent_with_watchdog

    job = {"id": "done-job", "name": "done", "schedule": {"kind": "interval", "minutes": 30}}
    fake_future = Future()
    fake_future.set_result({"final_response": "finished-work"})
    fake_pool = MagicMock()
    fake_pool.submit.return_value = fake_future
    cancel = threading.Event()
    # The cancel latched while the turn was already finishing: nothing it can interrupt remains.
    cancel.set()

    with patch("cron.scheduler.concurrent.futures.ThreadPoolExecutor", return_value=fake_pool), \
         patch("cron.scheduler.concurrent.futures.wait", return_value=({fake_future}, set())):
        result = _run_agent_with_watchdog(
            MagicMock(), "hello", job, job["id"], "done", "cron:done-job:t", cancel)

    assert result["final_response"] == "finished-work"

"""Regression for the unretained background-task class (cycle-3 c3-u2).

The gateway documents that a bare ``asyncio.create_task()`` is only weakly
referenced by the event loop (``gateway/run_shutdown.py``) and provides
``_retain_background_task`` for exactly that. The process-watcher fan-out
spawns long-lived watchers whose only job is to deliver a completion
notification; a GC pass mid-watch would silently drop that notification. The
contract: every watcher task scheduled by the fan-out is registered in the
retained set for as long as it is pending, and released once it completes.
"""

import asyncio

import pytest

from gateway import run_shutdown
from gateway import run_turn
from tools import process_registry


def _pending_watchers_in_retained_set():
    return [
        task
        for task in run_shutdown._RETAINED_BACKGROUND_TASKS
        if getattr(task.get_coro(), "__name__", "") == "_run_process_watcher"
    ]


@pytest.mark.asyncio
async def test_queued_watcher_task_is_retained_while_pending():
    class _WatchingTurn:
        async def _run_process_watcher(self, watcher):
            await asyncio.sleep(3600)

    assert list(process_registry.pending_watchers) == []
    spawned = []
    try:
        process_registry.pending_watchers = ["watcher-retention-1"]
        run_turn.GatewayTurnMixin._queue_process_watchers(_WatchingTurn())
        await asyncio.sleep(0.02)  # let the loop start the watcher

        spawned = _pending_watchers_in_retained_set()
        assert spawned, "watcher task was scheduled without a strong reference"
    finally:
        process_registry.pending_watchers = []
        for task in spawned:
            task.cancel()
        if spawned:
            await asyncio.gather(*spawned, return_exceptions=True)


@pytest.mark.asyncio
async def test_retained_watcher_is_released_after_completion():
    released = asyncio.Event()

    class _CompletingTurn:
        async def _run_process_watcher(self, watcher):
            released.set()

    assert list(process_registry.pending_watchers) == []
    try:
        process_registry.pending_watchers = ["watcher-retention-2"]
        run_turn.GatewayTurnMixin._queue_process_watchers(_CompletingTurn())
        await asyncio.wait_for(released.wait(), timeout=5)
        await asyncio.sleep(0.02)  # done-callbacks run on the loop

        assert _pending_watchers_in_retained_set() == [], (
            "retained set must not leak completed watcher tasks"
        )
    finally:
        process_registry.pending_watchers = []

"""Contract for the wire-task retention helper (cycle-3 c3-u2).

``GatewayWebsocket`` queues outbound batches and stalled-socket closes as
fire-and-forget tasks. A bare ``loop.create_task()`` is only weakly held by
the event loop; losing one silently drops a wire batch. The helper must (a)
hold a strong reference for the lifetime of the task and (b) drop it as soon
as the task completes so the set cannot grow unboundedly.
"""

import asyncio

import pytest

from tui_gateway import ws


@pytest.mark.asyncio
async def test_retain_task_holds_reference_until_completion():
    ran = asyncio.Event()

    async def work():
        await asyncio.sleep(0.05)
        ran.set()

    task = ws._retain_task(asyncio.get_running_loop().create_task(work()))
    try:
        assert task in ws._RETAINED_TASKS
        await asyncio.wait_for(ran.wait(), timeout=5)
        await asyncio.sleep(0.02)  # done-callbacks run on the loop
        assert task not in ws._RETAINED_TASKS, "completed tasks must be released"
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_retained_task_survives_a_garbage_collection_pass():
    ran = asyncio.Event()

    async def work():
        await asyncio.Event().wait()  # parked on an event nobody holds strongly
        ran.set()

    ws._retain_task(asyncio.get_running_loop().create_task(work()))
    import gc

    gc.collect()
    # The helper's contract is a live strong reference; after a forced GC the
    # set must still describe a pending task (not an empty or dead entry).
    pending = [t for t in ws._RETAINED_TASKS if not t.done()]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    assert pending, "retained fire-and-forget task vanished across a GC pass"

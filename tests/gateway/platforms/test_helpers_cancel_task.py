"""Bounded reap contract of ``gateway.platforms.helpers.cancel_task``.

The legacy contract (cancel + await, self-cancel safe, exception swallow) is covered by
``tests/gateway/test_shared_adapter_utils.py``. This file pins the bound added for the
CPython 3.11 cancel-eat class (#16645): a task whose body swallows CancelledError must not
be able to stall the caller forever — every platform adapter's teardown funnels through
this helper, so one pathological task otherwise hangs the whole gateway shutdown.
"""

import asyncio
import contextlib
import logging
import time

from gateway.platforms import helpers


def test_cancel_task_bounded_when_the_task_eats_cancellation(monkeypatch, caplog):
    monkeypatch.setattr(helpers, "_CANCEL_REAP_TIMEOUT", 0.25)

    async def scenario():
        stop = asyncio.Event()

        async def zombie():
            while not stop.is_set():
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    pass  # the pathological case: eat the cancel and keep running

        task = asyncio.create_task(zombie())
        await asyncio.sleep(0)
        try:
            with caplog.at_level(logging.WARNING, logger="gateway.platforms.helpers"):
                start = time.monotonic()
                await asyncio.wait_for(helpers.cancel_task(task), timeout=2.0)
                elapsed = time.monotonic() - start
            # The reap returned within its bound even though the task refused to unwind...
            assert elapsed < 2.0, f"cancel_task blocked {elapsed:.2f}s on a cancel-swallowing task"
            # ...the task was orphaned (still running, cancellation logged), not silently forgotten.
            assert not task.done()
            assert task.cancelling() == 1
            assert any("orphaning" in record.getMessage() for record in caplog.records)
        finally:
            # Cleanup: the zombie exits on stop + cancel instead of lingering into loop shutdown.
            stop.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(scenario())

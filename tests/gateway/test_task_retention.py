"""Unretained fire-and-forget dispatch lets the GC destroy in-flight work (rm-089).

asyncio keeps only a weak reference to a scheduled task. While a task sits in the ready
queue or is parked on an awaitable the loop pins (timers, transports), it survives by
accident — but a task parked on an awaitable nothing else references (a future, an event,
another bare task) forms an unreachable cycle and the next ``gc.collect()`` destroys the
work mid-flight ("Task was destroyed but it is pending"). The dispatch must therefore
retain its task; the shared bar is ``task_retention.retain_background_task`` and the
weixin long-poll dispatch is the site-level regression probe.
"""

from __future__ import annotations

import asyncio
import gc
import weakref

import pytest

from gateway.platforms import weixin as weixin_module


@pytest.mark.asyncio
async def test_unretained_task_is_collectable_mid_flight():
    """Why the class exists: a task nobody holds is destroyed while parked.

    The task parks on a future no one will ever set and no one else references; once the
    caller drops its reference the {task, future} cluster is unreachable and collectable.
    """
    loop = asyncio.get_running_loop()

    async def parks_forever():
        await loop.create_future()

    task = asyncio.create_task(parks_forever())
    ref = weakref.ref(task)
    await asyncio.sleep(0)  # let the task run its first step and park
    assert not task.done()

    del task
    gc.collect()
    assert ref() is None, "the task survived collection: this test's premise is stale"


@pytest.mark.asyncio
async def test_retention_helper_holds_until_completion():
    import task_retention

    done = asyncio.Event()

    async def work():
        await asyncio.sleep(0.01)
        done.set()

    task = task_retention.retain_background_task(asyncio.create_task(work()))
    assert task in task_retention.retained_tasks()
    await asyncio.wait_for(done.wait(), timeout=2.0)
    await asyncio.sleep(0)  # let the done callback run before asserting
    assert task not in task_retention.retained_tasks()


@pytest.mark.asyncio
async def test_poll_dispatch_retains_task_until_completion(monkeypatch, tmp_path):
    import task_retention

    adapter = object.__new__(weixin_module.WeixinAdapter)
    adapter._running = True
    adapter._poll_session = object()  # only the not-None assert in _poll_loop cares
    adapter._hermes_home = str(tmp_path)
    adapter._account_id = "acct"
    adapter._base_url = "https://example.invalid"
    adapter._token = None

    delivered = asyncio.Event()

    async def fake_process(message):
        await asyncio.sleep(0.05)
        delivered.set()

    monkeypatch.setattr(adapter, "_process_message", fake_process)
    monkeypatch.setattr(weixin_module, "_load_sync_buf", lambda home, account_id: "")

    async def fake_get_updates(session, *, base_url, token, sync_buf, timeout_ms):
        adapter._running = False  # one message batch, then the poll loop exits
        return {"msgs": [{"from_user_id": "user-1", "message_id": "m-1"}], "get_updates_buf": None}

    monkeypatch.setattr(weixin_module, "_get_updates", fake_get_updates)

    await adapter._poll_loop()

    # _poll_loop has returned: the dispatched task must be held by the retention set (an
    # unretained task is collectable at the next collection, per the class proof above).
    gc.collect()
    assert any(
        not t.done() for t in task_retention.retained_tasks()
    ), "weixin long-poll dispatch is not retained (rm-089)"

    await asyncio.wait_for(delivered.wait(), timeout=2.0)
    await asyncio.sleep(0)  # let the done callback release the slot
    assert not any(t.done() is False for t in task_retention.retained_tasks())

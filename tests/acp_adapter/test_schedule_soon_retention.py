"""Retention of ACP fire-and-forget work (cycle-3 c3-u2).

``AcpAgent._schedule_soon`` spawns usage flushes, title updates and prompt
drains as fire-and-forget tasks. A bare ``asyncio.create_task()`` is only
weakly held by the event loop; a GC pass would silently drop queued work.
The contract: every task spawned by ``_schedule_soon`` is referenced by the
agent instance while it is pending, and released once it completes.
"""

import asyncio

import pytest

from acp_adapter import server as acp_server
from acp_adapter.server import HermesACPAgent


def _make_agent():
    agent = HermesACPAgent.__new__(HermesACPAgent)
    agent._conn = object()  # non-None: scheduling is allowed
    if not hasattr(agent, "_retained_tasks"):
        # Base compatibility shim so the *behaviour*, not construction, is
        # what the assertion exercises.
        agent._retained_tasks = set()
    return agent


@pytest.mark.asyncio
async def test_scheduled_task_is_referenced_while_pending():
    agent = _make_agent()
    spawned = []
    started = asyncio.Event()

    async def work():
        started.set()
        spawned.append(asyncio.current_task())
        await asyncio.sleep(3600)

    agent._schedule_soon(work)
    await asyncio.wait_for(started.wait(), timeout=5)

    try:
        assert spawned, "scheduled coroutine never ran"
        assert spawned[0] in agent._retained_tasks, (
            "fire-and-forget task has no strong reference on the agent"
        )
    finally:
        for task in spawned:
            task.cancel()
        if spawned:
            await asyncio.gather(*spawned, return_exceptions=True)


@pytest.mark.asyncio
async def test_scheduled_task_is_released_after_completion():
    agent = _make_agent()
    done = asyncio.Event()

    async def work():
        done.set()

    agent._schedule_soon(work)
    await asyncio.wait_for(done.wait(), timeout=5)
    await asyncio.sleep(0.02)  # done-callbacks run on the loop

    assert [t for t in agent._retained_tasks if not t.done()] == [], (
        "retained set must not leak completed tasks"
    )

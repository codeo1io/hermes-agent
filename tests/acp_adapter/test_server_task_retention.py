"""ACP scheduled notification tasks must be retained and drained (cycle-3 W18).

``loop.call_soon(asyncio.create_task, ...)`` (and its threadsafe sibling for
title updates) leaves the spawned task referenced only by the ready queue — a GC
pass drops the session-update notification silently. The spawned tasks are now
tracked on the agent and drained at stdin-EOF shutdown (``acp_adapter/entry.py``
runs the drain after ``acp.run_agent`` returns), so the event loop never closes
over live notification work.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

import acp
from acp_adapter import entry
from acp_adapter.server import HermesACPAgent


def _bare_agent() -> HermesACPAgent:
    agent = HermesACPAgent.__new__(HermesACPAgent)
    agent._conn = MagicMock()
    agent._scheduled_tasks = set()
    return agent


class TestScheduledTaskRetention:
    @pytest.mark.asyncio
    async def test_scheduled_task_is_retained_while_running_and_drained(self):
        agent = _bare_agent()
        release = asyncio.Event()

        async def _notify():
            await release.wait()

        agent._schedule_soon(lambda: _notify())
        await asyncio.sleep(0)
        await asyncio.sleep(0)  # let the call_soon callback spawn the task

        assert len(agent._scheduled_tasks) == 1, "in-flight notification task must be retained"

        drain = asyncio.create_task(agent.drain_scheduled_tasks(timeout=2))
        release.set()
        await asyncio.wait_for(drain, timeout=5)
        assert not agent._scheduled_tasks

    @pytest.mark.asyncio
    async def test_drain_cancels_stragglers(self):
        agent = _bare_agent()
        cancelled = asyncio.Event()

        async def _stuck():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        agent._track_scheduled_task(asyncio.create_task(_stuck()))

        await asyncio.wait_for(agent.drain_scheduled_tasks(timeout=0.05), timeout=2)

        assert cancelled.is_set(), "a straggler past the drain bound must be cancelled"
        assert not agent._scheduled_tasks


class TestShutdownDrainWiring:
    def test_main_drains_scheduled_tasks_after_run_agent_returns(self, monkeypatch):
        """stdin EOF ends ``conn.listen()``; entry must drain in-flight notifications before the loop closes."""
        drained = []

        async def fake_run_agent(agent, **kwargs):
            return None

        async def fake_drain(self, timeout=5.0):
            drained.append(timeout)

        monkeypatch.setattr(entry, "_setup_logging", lambda: None)
        monkeypatch.setattr(entry, "_load_env", lambda: None)
        monkeypatch.setattr(acp, "run_agent", fake_run_agent)
        monkeypatch.setattr("acp_adapter.server.HermesACPAgent.drain_scheduled_tasks", fake_drain)

        entry.main([])

        assert drained, "stdin-EOF shutdown must drain in-flight scheduled notification tasks"

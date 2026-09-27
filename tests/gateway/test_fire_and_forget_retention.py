"""Fire-and-forget tasks must be retained: asyncio keeps only a WEAK reference to
a bare task, so dropping the strong reference lets the task be GC'd mid-flight —
a silently lost heartbeat, inbound handler, or browser-control WS frame (rm-034 /
I90 lineage; the qqbot fix lives inside the ``_create_task`` wrapper so no call
site can bypass retention, the api_server one at the on-loop send fast path).
"""

from __future__ import annotations

import asyncio

import gateway.platforms.api_server as api_server_mod
import gateway.platforms.qqbot.adapter as qqbot_mod
from gateway.platforms.api_server import _browser_controller_ws_sender
from gateway.platforms.qqbot.adapter import QQAdapter


class TestQQBotCreateTaskRetention:
    def test_wrapper_retains_task_until_done(self):
        """_create_task registers every task it schedules in _BACKGROUND_TASKS and
        discards it on completion (pre-fix: the wrapper returned the task and the
        call sites dropped it)."""
        pool = getattr(qqbot_mod, "_BACKGROUND_TASKS", None)
        assert pool is not None, "adapter module must expose _BACKGROUND_TASKS retention"
        ran = []

        async def work():
            ran.append(True)

        async def scenario():
            task = QQAdapter._create_task(work())
            assert task is not None
            assert task in pool, "scheduled task must be strongly retained"
            await asyncio.wait_for(task, timeout=5)
            await asyncio.sleep(0)  # let the done callback run
            assert task not in pool, "completed task must be discarded"

        asyncio.run(scenario())
        assert ran == [True]

    def test_wrapper_without_running_loop_returns_none(self):
        # Contract kept from the original wrapper: sync test call sites get None, not a raise.
        assert QQAdapter._create_task(_never_runs()) is None


async def _never_runs():
    raise AssertionError("this coroutine must never be scheduled")


class TestQQBotDispatchRoutesThroughWrapper:
    def test_inbound_handler_task_is_retained(self):
        """The MESSAGE dispatch site schedules _on_message through _create_task
        (pre-fix: a bare asyncio.create_task bypassed the wrapper's retention)."""
        pool = getattr(qqbot_mod, "_BACKGROUND_TASKS", None)
        assert pool is not None, "adapter module must expose _BACKGROUND_TASKS retention"
        adapter = QQAdapter.__new__(QQAdapter)
        handled = []

        async def fake_on_message(event_type, d):
            handled.append((event_type, d))

        adapter._on_message = fake_on_message
        adapter._session_id = None
        adapter._last_seq = None
        adapter._send_resume = None
        adapter._send_identify = None

        async def scenario():
            before = set(pool)
            adapter._dispatch_payload(
                {"op": 0, "t": "C2C_MESSAGE_CREATE", "s": 1, "d": {"id": "m1"}})
            new = set(pool) - before
            assert len(new) == 1, "inbound handler task must be retained, not dropped"
            await asyncio.wait_for(asyncio.gather(*new), timeout=5)
            await asyncio.sleep(0)
            assert set(pool) == before, "completed task must be discarded"

        asyncio.run(scenario())
        assert handled == [("C2C_MESSAGE_CREATE", {"id": "m1"})]


class _FakeWS:
    closed = False

    def __init__(self):
        self.frames = []

    async def send_json(self, frame):
        self.frames.append(frame)


class TestApiServerBrowserSendRetention:
    def test_on_loop_send_is_retained_until_done(self):
        """The on-loop fast path's send task is registered in
        _BACKGROUND_SEND_TASKS (pre-fix: bare loop.create_task, dropped reference)."""
        pool = getattr(api_server_mod, "_BACKGROUND_SEND_TASKS", None)
        assert pool is not None, "api_server module must expose _BACKGROUND_SEND_TASKS"
        ws = _FakeWS()

        async def scenario():
            loop = asyncio.get_running_loop()
            send = _browser_controller_ws_sender(ws, loop)
            before = set(pool)
            send({"op": "ping"})
            assert ws.frames == [], "frame not sent yet (send is async)"
            new = set(pool) - before
            assert len(new) == 1, "on-loop send task must be retained, not dropped"
            await asyncio.wait_for(asyncio.gather(*new), timeout=5)
            await asyncio.sleep(0)
            assert ws.frames == [{"op": "ping"}]
            assert set(pool) == before, "completed task must be discarded"

        asyncio.run(scenario())

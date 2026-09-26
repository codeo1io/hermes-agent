"""Fire-and-forget task retention at the three residual gateway create_task sites.

``asyncio`` keeps only weak references to tasks — an unreferenced task can be
collected mid-execution, silently dropping reconnects, message handlers, and
websocket frames. Three sites scheduled work without retaining the task:

- ``gateway/platforms/yuanbao.py`` ``schedule_reconnect`` (bare
  ``asyncio.create_task(self._reconnect_with_backoff())``) — beside in-tree
  retained precedents (``_track_task`` call sites);
- ``gateway/platforms/qqbot/adapter.py`` ``_dispatch_payload`` inbound branch
  (bypassed the file's own ``_create_task`` wrapper, which itself dropped the
  reference);
- ``gateway/platforms/api_server.py`` ``_browser_controller_ws_sender``
  (``loop.create_task(ws.send_json(frame))`` on-loop path).

Contract pinned per site: the scheduled task is held in a retention set while
in flight, survives a forced collection before its first step, completes, and
is then discarded — no set growth, no dropped work.
"""

from __future__ import annotations

import asyncio
import gc

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.api_server import _browser_controller_ws_sender
from gateway.platforms.qqbot.adapter import QQAdapter
from gateway.platforms.yuanbao import YuanbaoAdapter


def _yuanbao_config(**kwargs):
    extra = kwargs.pop("extra", {})
    extra.setdefault("app_id", "test_key")
    extra.setdefault("app_secret", "test_secret")
    extra.setdefault("ws_url", "wss://test.example.com/ws")
    extra.setdefault("api_domain", "https://test.example.com")
    return PlatformConfig(enabled=True, extra=extra)


def _qq_config(**extra):
    return PlatformConfig(enabled=True, extra={"app_id": "test-app", "client_secret": "test-secret", **extra})


class TestYuanbaoScheduleReconnectRetention:
    @pytest.mark.asyncio
    async def test_scheduled_reconnect_is_retained_and_survives_forced_gc(self):
        adapter = YuanbaoAdapter(_yuanbao_config())
        adapter._running = True
        adapter._connection._reconnecting = False

        adapter._connection.schedule_reconnect()

        retained = adapter._background_tasks
        assert len(retained) == 1, "reconnect task must be retained at schedule time"
        task = next(iter(retained))
        assert isinstance(task, asyncio.Task)

        gc.collect()  # an unreferenced task could be collected here
        assert not task.cancelled(), "retained reconnect task must survive forced collection"
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert not retained, "retention set must be empty after the task completes"

    @pytest.mark.asyncio
    async def test_scheduled_reconnect_calls_into_backoff(self):
        adapter = YuanbaoAdapter(_yuanbao_config())
        adapter._running = True
        adapter._connection._reconnecting = False
        started = asyncio.Event()

        async def fake_backoff():
            started.set()
            return True

        adapter._connection._reconnect_with_backoff = fake_backoff
        adapter._connection.schedule_reconnect()
        await asyncio.wait_for(started.wait(), timeout=2.0)
        # Let the done callback drain the set.
        await asyncio.sleep(0)
        assert not adapter._background_tasks


class TestQQBotDispatchRetention:
    @pytest.mark.asyncio
    async def test_inbound_dispatch_task_is_retained_and_runs(self):
        adapter = QQAdapter(_qq_config())
        handled = asyncio.Event()

        async def fake_on_message(event_type, d):
            handled.set()

        adapter._on_message = fake_on_message
        adapter._dispatch_payload({"op": 0, "t": "C2C_MESSAGE_CREATE", "s": 1, "d": {"id": "m1"}})

        assert len(adapter._background_tasks) == 1, "inbound handler task must be retained"
        task = next(iter(adapter._background_tasks))

        gc.collect()
        await asyncio.wait_for(handled.wait(), timeout=2.0)
        await asyncio.sleep(0)
        assert task.done()
        assert not adapter._background_tasks, "retention set must drain on completion"

    @pytest.mark.asyncio
    async def test_create_task_returns_none_without_running_loop(self):
        # Tests (and any sync caller) reach _dispatch_payload with no loop: the
        # wrapper must swallow the RuntimeError, not raise.
        adapter = QQAdapter(_qq_config())

        async def noop():
            return None

        coro = noop()

        def sync_call():
            return adapter._create_task(coro)  # executor thread: no running loop

        result = await asyncio.get_running_loop().run_in_executor(None, sync_call)
        assert result is None
        coro.close()  # never scheduled: close so it does not warn


class TestApiServerWsSenderRetention:
    @pytest.mark.asyncio
    async def test_on_loop_send_task_is_retained_and_frame_delivered(self):
        loop = asyncio.get_running_loop()
        delivered = asyncio.Event()
        seen: list[dict] = []

        class FakeWS:
            closed = False

            async def send_json(self, frame):
                await asyncio.sleep(0.05)  # suspension point: retention carries the frame
                seen.append(frame)
                delivered.set()

        sender = _browser_controller_ws_sender(FakeWS(), loop)
        sender({"kind": "hello"})

        gc.collect()  # an unreferenced send task could be collected here
        await asyncio.wait_for(delivered.wait(), timeout=2.0)
        assert seen == [{"kind": "hello"}]
        await asyncio.sleep(0)
        from gateway.platforms import api_server
        assert not api_server._ws_send_tasks, "retention set must drain after delivery"

"""The scheduled Yuanbao reconnect must be retained and cancellable (cycle-3 W18).

``ConnectionManager.schedule_reconnect`` spawned its backoff task with a bare
``asyncio.create_task`` — the loop's ready queue held the only strong reference,
so a GC pass mid-backoff dropped the reconnect silently (dead WS, no retry, no
error). The file's own ``YuanbaoAdapter._track_task`` retention (already used at
:620/:1020/:2073) is the fix: the task lands in ``_background_tasks`` and the
gateway's shutdown drain (``cancel_background_tasks``) can see and cancel it.
"""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.platforms.yuanbao import ConnectionManager, YuanbaoAdapter


def _make_adapter():
    adapter = MagicMock(spec=YuanbaoAdapter)
    adapter._running = True
    adapter._background_tasks = set()
    # Bind the real retention method so the set behaves exactly like production.
    adapter._track_task = YuanbaoAdapter._track_task.__get__(adapter)
    return adapter


class TestReconnectTaskRetention:
    @pytest.mark.asyncio
    async def test_scheduled_reconnect_is_tracked_and_cancellable(self):
        adapter = _make_adapter()
        cm = ConnectionManager(adapter)
        started = asyncio.Event()

        async def _slow_reconnect():
            started.set()
            await asyncio.sleep(30)  # backoff/attempt still in flight at shutdown

        try:
            with patch.object(cm, "_reconnect_with_backoff", _slow_reconnect):
                cm.schedule_reconnect()
                await asyncio.wait_for(started.wait(), timeout=2)

                tracked = adapter._background_tasks
                assert len(tracked) == 1, "reconnect task must be retained (gateway shutdown drains this set)"
                task = next(iter(tracked))

                # The shutdown drain (gateway cancel_background_tasks): cancel + await.
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                assert not adapter._background_tasks, "done-callback must discard the finished task"
        finally:
            for leftover in asyncio.all_tasks() - {asyncio.current_task()}:
                leftover.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await leftover

    @pytest.mark.asyncio
    async def test_guards_still_hold(self):
        adapter = _make_adapter()
        cm = ConnectionManager(adapter)
        reconnect = AsyncMock()

        with patch.object(cm, "_reconnect_with_backoff", reconnect):
            adapter._running = False
            cm.schedule_reconnect()
            assert not reconnect.called

            adapter._running = True
            cm._reconnecting = True
            cm.schedule_reconnect()
            assert not reconnect.called
            assert adapter._background_tasks == set()

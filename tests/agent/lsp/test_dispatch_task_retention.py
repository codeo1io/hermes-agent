"""Retention of in-flight LSP request-dispatch tasks: the event loop only keeps weak
references to tasks, so an unreferenced dispatch task can be garbage-collected mid-await —
before its response is sent — which the server experiences as a dropped request."""

import asyncio
import gc

from agent.lsp.client import LSPClient


def _request_msg() -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": "workspace/executeCommand", "params": {}}


def test_request_dispatch_task_is_retained(tmp_path):
    async def scenario():
        client = LSPClient(server_id="test-server", workspace_root=str(tmp_path), command=["unused-command"])

        async def fake_dispatch_request(key, msg):
            # A bare future held only by this coroutine's frame: with no external reference,
            # the task+future cycle is collectible, which is exactly the GC window the
            # retention set has to survive.
            await asyncio.get_running_loop().create_future()

        client._dispatch_request = fake_dispatch_request
        client._dispatch(_request_msg())
        await asyncio.sleep(0)  # let the dispatch task take its first step (mid-await)
        gc.collect()

        assert client._dispatch_tasks, "dispatch task was garbage-collected before its response was sent"

        for pending in list(client._dispatch_tasks):
            pending.cancel()
        await asyncio.gather(*client._dispatch_tasks, return_exceptions=True)
        assert not client._dispatch_tasks  # done callback removed the finished task

    asyncio.run(scenario())

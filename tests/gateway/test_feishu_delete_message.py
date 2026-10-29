"""Feishu message deletion contract, isolated from the large adapter suite."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests.gateway.feishu_helpers import clear_feishu_env


@clear_feishu_env
class TestDeleteMessage(unittest.TestCase):
    def test_delete_message_calls_im_message_delete(self):
        from gateway.config import PlatformConfig
        from plugins.platforms.feishu.adapter import FeishuAdapter

        captured = {"ids": []}

        class _MessageAPI:
            def delete(self, request):
                captured["ids"].append(getattr(request, "message_id", None))
                return SimpleNamespace(success=lambda: True)

        adapter = FeishuAdapter(PlatformConfig())
        adapter._client = SimpleNamespace(
            im=SimpleNamespace(v1=SimpleNamespace(message=_MessageAPI()))
        )

        async def _direct(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch.object(adapter, "_run_blocking", side_effect=_direct):
            ok = asyncio.run(adapter.delete_message("oc_chat", "om_preview"))

        self.assertTrue(ok)
        self.assertEqual(captured["ids"], ["om_preview"])

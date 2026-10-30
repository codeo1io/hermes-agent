"""Shared hermetic home pin for Feishu adapter tests (see test_feishu.py).

The adapter classes that wipe ``os.environ`` construct ``FeishuAdapter`` with no
HERMES_HOME, so its dedup store resolves through the passwd-backed platform
default — the operator's real ``~/.hermes`` — tripping the home-io guard and, on
a live host, touching real state. This mixin pins the adapter's own
``get_hermes_home`` to a per-test scratch dir for the whole test (the same pin
``test_concurrent_dedup_persists_land_in_order`` applies inline). Also hosts the
relocated ``TestFeishuNormalizeText`` (file-lines ratchet: test_feishu.py may only shrink).
"""

from __future__ import annotations

import unittest

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch


class PinnedAdapterHomeMixin:
    def setUp(self):
        super().setUp()
        self._adapter_home = tempfile.mkdtemp(prefix="feishu-adapter-home-")
        patcher = patch(
            "plugins.platforms.feishu.adapter.get_hermes_home",
            return_value=Path(self._adapter_home),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self._adapter_home, ignore_errors=True)
        super().tearDown()

class TestFeishuNormalizeText(unittest.TestCase):

    def test_renders_self_mention_with_name(self):
        from plugins.platforms.feishu.adapter import _normalize_feishu_text, FeishuMentionRef

        refs = {"@_user_1": FeishuMentionRef(name="Hermes", open_id="ou_bot", is_self=True)}
        self.assertEqual(
            _normalize_feishu_text("stop pinging @_user_1 please", refs),
            "stop pinging @Hermes please",
        )

    def test_at_all_rendered_as_english_literal(self):
        from plugins.platforms.feishu.adapter import _normalize_feishu_text

        self.assertEqual(_normalize_feishu_text("@_all notice", None), "@all notice")


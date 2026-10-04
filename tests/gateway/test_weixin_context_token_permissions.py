"""Weixin context-token files are live pairing secrets and must be owner-only (cycle-3 W15).

``ContextTokenStore`` persists the live per-peer context tokens that authorize bot
sends on the iLink channel — the same sensitivity class as the QR-paired account
file (``save_weixin_account`` → 0o600, probed 0o600 on disk). ``_persist`` used to
write at umask default (0o664 on typical hosts), and ``restore()`` left a
pre-existing group/world-readable file untouched: tokens readable by every local
user, and re-pairing the account did not fix the mode of the file already on disk.
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from gateway.platforms.weixin import ContextTokenStore

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")


class TestContextTokenPermissions:
    @posix_only
    def test_persist_writes_owner_only_mode(self, tmp_path: Path):
        store = ContextTokenStore(str(tmp_path))
        asyncio.run(store.set("acct", "wxid_user", "ctx-token-1"))

        path = tmp_path / "weixin" / "accounts" / "acct.context-tokens.json"
        assert path.exists()
        assert path.stat().st_mode & 0o777 == 0o600
        # Payload/round-trip unchanged by the permission fix.
        assert json.loads(path.read_text(encoding="utf-8")) == {"wxid_user": "ctx-token-1"}
        assert store.get("acct", "wxid_user") == "ctx-token-1"

    @posix_only
    def test_restore_repairs_preexisting_group_readable_file(self, tmp_path: Path):
        # A file persisted world-readable by an older build (or a restored backup).
        path = tmp_path / "weixin" / "accounts" / "acct.context-tokens.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"wxid_user": "leaked-token"}), encoding="utf-8")
        path.chmod(0o664)

        store = ContextTokenStore(str(tmp_path))
        store.restore("acct")

        assert path.stat().st_mode & 0o777 == 0o600
        assert store.get("acct", "wxid_user") == "leaked-token"

    @posix_only
    def test_restore_leaves_already_private_file_untouched(self, tmp_path: Path):
        path = tmp_path / "weixin" / "accounts" / "acct.context-tokens.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"wxid_user": "tok"}), encoding="utf-8")
        path.chmod(0o600)

        ContextTokenStore(str(tmp_path)).restore("acct")

        assert path.stat().st_mode & 0o777 == 0o600

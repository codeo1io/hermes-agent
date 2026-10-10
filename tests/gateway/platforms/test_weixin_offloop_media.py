"""Weixin outbound media: file read, md5, and AES-ECB must run off the event loop.

Regression for the cycle-2 assess finding (gateway/platforms/weixin.py:1134-1142):
``_send_file`` read the payload, hashed it, and ran the AES-ECB encrypt pass
synchronously on the loop — a multi-MB video stalls every other session's
stream on a busy gateway. The fix dispatches all three to worker threads and
refuses over-cap files locally before reading them (parity with
whatsapp_cloud's outbound per-type caps).
"""

import hashlib
import threading
from unittest.mock import patch

import pytest

from gateway.platforms import weixin
from gateway.platforms.weixin import WeixinAdapter



class _StopAfterCrypto(Exception):
    """Raised by the AES recorder once the off-loop dispatch is proven."""


@pytest.fixture
def adapter():
    with patch.object(WeixinAdapter, "__init__", lambda self, cfg: None):
        a = WeixinAdapter.__new__(WeixinAdapter)
    a._send_session = object()
    a._token = "t"
    a._base_url = "https://ilinkai.weixin.qq.com"
    a._account_id = "acct"
    a._cdn_base_url = "https://novac2c.cdn.weixin.qq.com/c2c"
    return a


@pytest.mark.asyncio
async def test_send_file_media_io_and_crypto_run_off_loop(tmp_path, monkeypatch, adapter):
    """read_bytes / md5 / AES each run on a worker thread, never the loop thread."""
    payload = b"PNGDATA" * 8
    media = tmp_path / "clip.png"
    media.write_bytes(payload)

    seen = {}

    def _record_read():
        seen["read_thread"] = threading.get_ident()
        return payload

    def _record_md5(data):
        seen["md5_thread"] = threading.get_ident()
        # hashlib.md5 is patched below (it is the module-level reference the
        # production code resolves); use the digest constructor to get the real one.
        return hashlib.new("md5", data)

    def _record_encrypt(data, key):
        seen["aes_thread"] = threading.get_ident()
        raise _StopAfterCrypto()

    monkeypatch.setattr(weixin.Path, "read_bytes", lambda self: _record_read())
    monkeypatch.setattr(weixin.hashlib, "md5", _record_md5)
    monkeypatch.setattr(weixin, "_aes128_ecb_encrypt", _record_encrypt)

    async def _fake_upload_url(*args, **kwargs):
        return {"upload_full_url": "https://cdn/upload"}

    monkeypatch.setattr(weixin, "_get_upload_url", _fake_upload_url)

    with pytest.raises(_StopAfterCrypto):
        await adapter._send_file("chat", str(media), "")

    loop_thread = threading.get_ident()
    assert seen["read_thread"] != loop_thread, "payload read must be dispatched off-loop"
    assert seen["md5_thread"] != loop_thread, "md5 pass must be dispatched off-loop"
    assert seen["aes_thread"] != loop_thread, "AES-ECB pass must be dispatched off-loop"


@pytest.mark.asyncio
async def test_send_file_refuses_oversized_file_before_reading(tmp_path, monkeypatch, adapter):
    """An over-cap file becomes a clean ValueError without a single byte read."""
    monkeypatch.setattr(weixin, "MAX_OUTBOUND_MEDIA_BYTES", 8)
    media = tmp_path / "huge.png"
    media.write_bytes(b"x" * 16)

    def _must_not_read(self):
        raise AssertionError("oversized file must be refused before any read")

    monkeypatch.setattr(weixin.Path, "read_bytes", _must_not_read)

    with pytest.raises(ValueError, match="outbound file too large"):
        await adapter._send_file("chat", str(media), "")

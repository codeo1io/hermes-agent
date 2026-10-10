"""WhatsApp Cloud inbound media: streamed under a hard cap, cached off-loop.

Regression for the cycle-2 assess finding (gateway/platforms/whatsapp_cloud.py:655-661):
the Graph blob leg fully buffered ``resp.content`` (an attacker-sized signed URL
decides the size) and then mkdir+write_bytes ran on the loop. The fix streams the
download with a byte ceiling (pre-checked from Content-Length, enforced mid-read)
and dispatches the cache write to a worker thread.
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

from gateway.platforms import whatsapp_cloud as wa
from gateway.platforms.whatsapp_cloud import WhatsAppCloudAdapter


class _StreamResp:
    def __init__(self, status_code: int, body: bytes, content_length: str | None = None):
        self.status_code = status_code
        self._body = body
        self.headers = {"Content-Length": content_length if content_length is not None else str(len(body))}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aiter_bytes(self):
        yield self._body


@pytest.fixture
def adapter():
    with patch.object(WhatsAppCloudAdapter, "__init__", lambda self, cfg: None):
        a = WhatsAppCloudAdapter.__new__(WhatsAppCloudAdapter)
    a._http_client = MagicMock()
    a._access_token = "test-token"
    a._api_version = "v21.0"
    return a


def _metadata_client(adapter, body: bytes, content_length: str | None = None, status: int = 200):
    """Wire the two GET legs: small metadata JSON (buffered) + blob stream."""
    meta = MagicMock()
    meta.json.return_value = {"url": "https://lookaside.facebook.com/blob", "mime_type": "audio/ogg"}

    async def _fake_graph_get(url, headers, what, media_id):  # noqa: ARG001
        return meta

    adapter._graph_get = _fake_graph_get

    def _stream(method, url, headers=None):  # noqa: ARG001 - httpx stream() returns the CM synchronously
        return _StreamResp(status, body, content_length)

    adapter._http_client.stream = _stream
    return meta


def _cache_dir(tmp_path):
    """Dedicated cache dir: the conftest isolation fixture also writes into tmp_path."""
    cache = tmp_path / "media-cache"
    cache.mkdir()
    return cache


@pytest.mark.asyncio
async def test_blob_write_runs_off_loop(tmp_path, monkeypatch, adapter):
    """Cache mkdir + write_bytes run on a worker thread, never the loop thread."""
    blob = b"MEDIA" * 4
    _metadata_client(adapter, blob)
    cache = _cache_dir(tmp_path)
    monkeypatch.setattr(wa, "_INBOUND_MEDIA_CACHE", cache)

    seen = {}
    real_write = wa.Path.write_bytes
    real_mkdir = wa.Path.mkdir

    def _record_write(self, data):
        seen["write_thread"] = threading.get_ident()
        return real_write(self, data)

    def _record_mkdir(self, *args, **kwargs):
        seen["mkdir_thread"] = threading.get_ident()
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(wa.Path, "write_bytes", _record_write)
    monkeypatch.setattr(wa.Path, "mkdir", _record_mkdir)

    path, mime = await adapter._download_media_to_cache("m123", ext_hint=".ogg")

    loop_thread = threading.get_ident()
    assert seen["mkdir_thread"] != loop_thread, "cache mkdir must be dispatched off-loop"
    assert seen["write_thread"] != loop_thread, "blob write must be dispatched off-loop"
    assert path == str(cache / "m123.ogg") and mime == "audio/ogg"
    assert (cache / "m123.ogg").read_bytes() == blob


@pytest.mark.asyncio
async def test_oversized_content_length_refused_without_download(tmp_path, monkeypatch, adapter):
    """A declared Content-Length over the cap is refused before the body streams."""
    monkeypatch.setattr(wa, "_INBOUND_MEDIA_MAX_BYTES", 8)
    _metadata_client(adapter, b"", content_length="9")
    cache = _cache_dir(tmp_path)
    monkeypatch.setattr(wa, "_INBOUND_MEDIA_CACHE", cache)

    assert await adapter._download_media_to_cache("m123") == (None, None)
    assert list(cache.iterdir()) == [], "nothing may be cached for a refused blob"


@pytest.mark.asyncio
async def test_cap_enforced_mid_download_when_length_lies(tmp_path, monkeypatch, adapter):
    """A lying Content-Length is still stopped: the read aborts once the cap is crossed."""
    monkeypatch.setattr(wa, "_INBOUND_MEDIA_MAX_BYTES", 8)
    _metadata_client(adapter, b"x" * 16, content_length="4")  # small lie, double-the-cap body
    cache = _cache_dir(tmp_path)
    monkeypatch.setattr(wa, "_INBOUND_MEDIA_CACHE", cache)

    assert await adapter._download_media_to_cache("m123") == (None, None)
    assert list(cache.iterdir()) == [], "nothing may be cached for an over-cap blob"


@pytest.mark.asyncio
async def test_non_200_blob_is_clean_failure(tmp_path, monkeypatch, adapter):
    """A failed blob fetch still returns (None, None) with nothing cached."""
    _metadata_client(adapter, b"", status=403)
    cache = _cache_dir(tmp_path)
    monkeypatch.setattr(wa, "_INBOUND_MEDIA_CACHE", cache)

    assert await adapter._download_media_to_cache("m123") == (None, None)
    assert list(cache.iterdir()) == []

"""qqbot voice pipeline: converted-wav read and unlink must run off the event loop.

Regression for the cycle-2 assess finding (gateway/platforms/qqbot/adapter.py:1270-1280):
``_convert_audio_to_wav`` read the converted wav into memory and unlinked it
synchronously on the loop. Voice wavs are real audio payloads — the blocking
pair stalled the gateway's streaming contract.
"""

import threading
from unittest.mock import patch

import pytest

from gateway.platforms.qqbot import adapter as qq_mod
from gateway.platforms.qqbot.adapter import QQAdapter


@pytest.fixture
def adapter():
    with patch.object(QQAdapter, "__init__", lambda self, cfg: None):
        a = QQAdapter.__new__(QQAdapter)
    return a


@pytest.mark.asyncio
async def test_wav_read_and_unlink_run_off_loop(tmp_path, monkeypatch, adapter):
    """read_bytes and os.unlink each run on a worker thread, never the loop thread."""
    wav_bytes = b"WAVDATA" * 4
    wav = tmp_path / "conv.wav"
    wav.write_bytes(wav_bytes)
    src = tmp_path / "src.mp3"
    src.write_bytes(b"SRC")

    seen = {}
    real_read = qq_mod.Path.read_bytes
    real_unlink = qq_mod.os.unlink

    def _record_read(self):
        seen["read_thread"] = threading.get_ident()
        return real_read(self)

    def _record_unlink(path, *args, **kwargs):
        seen["unlink_thread"] = threading.get_ident()
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(qq_mod.Path, "read_bytes", _record_read)
    monkeypatch.setattr(qq_mod.os, "unlink", _record_unlink)

    async def _fake_cache(data, filename):
        assert data == wav_bytes
        seen["cached"] = filename
        return "cache://voice"

    monkeypatch.setattr(qq_mod, "cache_document_from_bytes_async", _fake_cache)

    # Instance-level seams: temp pairing, format sniffing, and the conversion step
    # itself are upstream of the read/unlink pair under test.
    adapter._temp_pair = lambda audio_data, ext: (str(src), str(wav))
    adapter._looks_like_silk = lambda audio_data: False
    adapter._unlink_quiet = lambda path: None

    async def _fake_convert(src_path, wav_path):  # noqa: ARG001 - conversion is faked
        return True

    adapter._convert_ffmpeg_to_wav = _fake_convert

    out = await adapter._convert_audio_to_wav(b"SRC", "https://dl.example.com/v.mp3")

    assert out == "cache://voice" and seen["cached"] == "qq_voice.wav"
    assert not wav.exists(), "converted wav must still be unlinked after the read"
    loop_thread = threading.get_ident()
    assert seen["read_thread"] != loop_thread, "wav read must be dispatched off-loop"
    assert seen["unlink_thread"] != loop_thread, "unlink must be dispatched off-loop"


@pytest.mark.asyncio
async def test_missing_wav_after_conversion_returns_none(tmp_path, monkeypatch, adapter):
    """A wav that vanishes before the read still returns None (failure semantics preserved)."""
    src = tmp_path / "src.mp3"
    src.write_bytes(b"SRC")

    async def _fake_cache(data, filename):  # pragma: no cover - must not be reached
        raise AssertionError("cache must not be called for a vanished wav")

    monkeypatch.setattr(qq_mod, "cache_document_from_bytes_async", _fake_cache)
    adapter._temp_pair = lambda audio_data, ext: (str(src), str(tmp_path / "absent.wav"))
    adapter._looks_like_silk = lambda audio_data: False
    adapter._unlink_quiet = lambda path: None

    async def _fake_convert(src_path, wav_path):  # noqa: ARG001
        return True

    adapter._convert_ffmpeg_to_wav = _fake_convert

    assert await adapter._convert_audio_to_wav(b"SRC", "https://dl.example.com/v.mp3") is None

"""vision_tools terminal-backend video materialization must run off the event loop.

Regression for the cycle-2 assess finding (tools/vision_tools.py:992-994): the
terminal-backend branch of ``_materialize_video`` mkdir'ed the temp dir and
wrote the resolved bytes synchronously on the loop while the provider-backed
branch (:551) already dispatched to a worker thread. Terminal-backend payloads
are real videos — often tens of MB.
"""

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import vision_tools
import tools.image_source as image_source_mod


@pytest.mark.asyncio
async def test_terminal_video_write_runs_off_loop(tmp_path, monkeypatch):
    """Temp-dir mkdir and the byte write run on a worker thread, never the loop."""
    seen = {}
    real_write = Path.write_bytes
    real_mkdir = Path.mkdir

    def _record_write(self, data):
        seen["write_thread"] = threading.get_ident()
        return real_write(self, data)

    def _record_mkdir(self, *args, **kwargs):
        seen["mkdir_thread"] = threading.get_ident()
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_bytes", _record_write)
    monkeypatch.setattr(Path, "mkdir", _record_mkdir)

    payload = b"VIDEOBYTES" * 512

    async def _fake_resolve(video_url, context, permitted):  # noqa: ARG001
        assert permitted == ("video",)
        return SimpleNamespace(data=payload)

    # _materialize_video imports both names from tools.image_source inside the
    # function body, so the module attributes are the seam.
    monkeypatch.setattr(image_source_mod, "_is_local_terminal_backend", lambda: False)
    monkeypatch.setattr(image_source_mod, "resolve_image_source", _fake_resolve)

    temp_paths: list = []
    out = await vision_tools._materialize_video("vid.mp4", "task-1", temp_paths)

    loop_thread = threading.get_ident()
    assert seen["mkdir_thread"] != loop_thread, "temp-dir mkdir must be dispatched off-loop"
    assert seen["write_thread"] != loop_thread, "video write must be dispatched off-loop"
    assert out.exists() and out.read_bytes() == payload
    assert temp_paths == [out], "created file must be tracked for later cleanup"

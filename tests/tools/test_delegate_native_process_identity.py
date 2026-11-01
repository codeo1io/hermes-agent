"""Process-incarnation identity is distinct from the durable session creation time."""

import os
from pathlib import Path
from types import SimpleNamespace

from tools import delegate_session_tool as ds


def _stat(ppid: int, ticks: int) -> str:
    # /proc/<pid>/stat fields after ") ": state, ppid, then 17 fields
    # before field 22 (starttime).
    return f"4242 (pi) S {ppid} " + " ".join(["0"] * 17) + f" {ticks} 0 0"


def test_pi_process_incarnation_persisted_independently_of_created_at(monkeypatch):
    real_read = Path.read_text
    monkeypatch.setattr(
        Path, "read_text",
        lambda self, *a, **kw: _stat(os.getpid(), 98765)
        if str(self) == "/proc/4242/stat" else real_read(self, *a, **kw),
    )
    client = SimpleNamespace(_proc=SimpleNamespace(pid=4242, poll=lambda: None))
    identity = ds._native_process_identity(client)
    assert identity == {"pid": 4242, "start_ticks": 98765, "ppid": os.getpid()}
    snapshot = ds._metadata_snapshot({
        "session_id": "old-session", "backend": "pi",
        "created_at": 100.0, "updated_at": 200.0,
        "native_process": identity,
    })
    assert snapshot["created_at"] == 100.0
    assert snapshot["native_process"] == identity


def test_pi_process_identity_refuses_unproven_process(monkeypatch):
    real_read = Path.read_text
    monkeypatch.setattr(
        Path, "read_text",
        lambda self, *a, **kw: _stat(os.getpid() + 1, 98765)
        if str(self) == "/proc/4242/stat" else real_read(self, *a, **kw),
    )
    live = SimpleNamespace(_proc=SimpleNamespace(pid=4242, poll=lambda: None))
    assert ds._native_process_identity(live) is None
    assert ds._native_process_identity(SimpleNamespace(_proc=None)) is None
    assert ds._native_process_identity(
        SimpleNamespace(_proc=SimpleNamespace(pid=4242, poll=lambda: 1))
    ) is None


def test_pi_process_identity_refuses_corrupt_proc_stat(monkeypatch):
    real_read = Path.read_text
    monkeypatch.setattr(
        Path, "read_text",
        lambda self, *a, **kw: "bad-stat"
        if str(self) == "/proc/4242/stat" else real_read(self, *a, **kw),
    )
    client = SimpleNamespace(_proc=SimpleNamespace(pid=4242, poll=lambda: None))
    assert ds._native_process_identity(client) is None

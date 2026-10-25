"""Offline `messages` reads must not launder completed turns into zero-output.

Regression coverage for the msn-exec06-003 incident (2026-10-25): a turn
that completes just as the in-process registry loses its record (spool
restart race, close race) must be judged on the durable record's tail, not
on an empty message array.
"""

from __future__ import annotations

import json
import threading

import pytest

import tools.delegate_session_tool as ds
from agent.delegate_health import reset_delegate_health_ledger


class Parent:
    def __init__(self, session_id: str = "parent-session") -> None:
        self.session_id = session_id


class FakePiClient:
    """Minimal stand-in mirroring the contract the real PiRPCClient exposes
    (subset of tests/tools/test_delegate_session_tool.py's fake)."""

    def __init__(
        self,
        *,
        persistent_session=False,
        session_id=None,
        session_name=None,
        acp_cwd=None,
        question_answerer=None,
        **_kwargs,
    ) -> None:
        self.persistent_session = persistent_session
        self.session_id = session_id
        self.session_name = session_name
        self.cwd = acp_cwd
        self.question_answerer = question_answerer
        self.is_closed = False
        self.messages: list[str] = []
        self.started_turn = threading.Event()
        self.release_turn = threading.Event()
        self.block_turns = False
        self.last_turn_activity_at = 0.0

    def start(self, *, timeout=30.0, stages=None):
        return {
            "sessionId": self.session_id,
            "sessionFile": f"/tmp/{self.session_id}.jsonl",
            "messageCount": len(self.messages),
            "isStreaming": False,
        }

    def run_session_prompt(self, message, *, timeout_seconds=900.0):
        self.messages.append(message)
        self.started_turn.set()
        if self.block_turns:
            assert self.release_turn.wait(timeout=5)
        return {
            "success": True,
            "text": f"done:{message}",
            "reasoning": "",
            "duration_s": 0.01,
            "state": {
                "sessionId": self.session_id,
                "messageCount": len(self.messages),
                "isStreaming": False,
            },
        }

    def get_messages(self, *, timeout=30.0, stages=None):
        return [{"role": "user", "content": m} for m in self.messages]

    def steer(self, message, *, timeout=30.0, stages=None):
        return {"success": True, "command": "steer"}

    def abort(self, *, timeout=30.0):
        self.release_turn.set()
        return {"success": True, "command": "abort"}

    def close(self):
        self.is_closed = True
        self.release_turn.set()


@pytest.fixture(autouse=True)
def clean_sessions(monkeypatch, tmp_path):
    reset_delegate_health_ledger()
    with ds._SESSION_LOCK:
        for record in ds._SESSIONS.values():
            try:
                record["client"].close()
            except Exception:
                pass
        ds._SESSIONS.clear()
    monkeypatch.setattr(ds, "PiRPCClient", FakePiClient)
    monkeypatch.setattr(ds, "resolve_agent_cwd", lambda: tmp_path)
    monkeypatch.setattr(
        ds, "_session_store_root", lambda: tmp_path / "delegate-session-store"
    )
    monkeypatch.setattr(ds, "pending_question_for_owner", lambda _client: None)
    yield
    with ds._SESSION_LOCK:
        for record in ds._SESSIONS.values():
            try:
                record["client"].close()
            except Exception:
                pass
        ds._SESSIONS.clear()


def payload(raw: str) -> dict:
    return json.loads(raw)


def test_offline_messages_surfaced_durable_tail_after_close_race():
    """msn-exec06-003 regression (2026-10-25): a turn that completes just as
    the registry loses the record (restart/close race) must NOT read as
    "zero output". The durable metadata carries the completed turn's tail
    (last_line); the offline messages fallback surfaces it as a synthetic
    final assistant row so downstream proof-of-answer gates judge the turn
    on the durable record instead of an empty array."""
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    # Simulate a completed turn's durable evidence.
    with ds._SESSION_LOCK:
        record = ds._SESSIONS[sid]
        record["last_line"] = (
            "I'm a dispatched delegate. The work is complete; here is the tail."
        )
        record["last_turn_outcome"] = "completed"
    ds._persist_metadata(record)
    with ds._SESSION_LOCK:
        stale = ds._SESSIONS.pop(sid)
    stale["client"].close()

    messages = payload(
        ds.delegate_session(action="messages", session_id=sid, parent_agent=parent)
    )
    assert messages["success"] is True
    rows = json.loads(messages["messages_json"])
    assert len(rows) == 1
    row = rows[0]
    assert row["role"] == "assistant"
    assert row["_offline_tail"] is True
    text = row["content"][0]["text"]
    assert "work is complete" in text
    assert "resume" in (messages.get("note") or "").lower()


def test_offline_messages_stays_empty_without_durable_tail():
    """No durable tail (a session that never produced a completed turn)
    keeps the honest empty list — the synthetic row appears ONLY when the
    durable record actually carries tail evidence."""
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    with ds._SESSION_LOCK:
        record = ds._SESSIONS[sid]
        record["last_line"] = ""
        record["salvage_tail"] = None
    ds._persist_metadata(record)
    with ds._SESSION_LOCK:
        stale = ds._SESSIONS.pop(sid)
    stale["client"].close()

    messages = payload(
        ds.delegate_session(action="messages", session_id=sid, parent_agent=parent)
    )
    assert messages["success"] is True
    assert messages["messages_json"] == "[]"

"""Offline `messages` reads must not launder completed turns into zero-output.

Regression coverage extracted from test_delegate_session_tool.py (2026-10-25)
after the msn-exec06-003 incident: a turn that completes just as the
in-process registry loses its record (spool restart race, close race) must be
judged on the durable record's tail, not on an empty message array.
"""

from __future__ import annotations

import json

import tools.delegate_session_tool as ds


class Parent:
    def __init__(self, session_id: str = "parent-session") -> None:
        self.session_id = session_id


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

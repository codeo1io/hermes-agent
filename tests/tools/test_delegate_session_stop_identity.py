"""Stop must not launder an interrupted (resumable) session into evictable terminal state.

Regression class: M5 native recovery (msn-m5-opencode-recovery-004 et al.).
The spool server's release path calls action=stop on a session whose turn
failed (status=error). The old stop handler rewrote status to "closed"
unconditionally, so the durable record — the ONLY mapping from the Hermes
delegate handle to the native OpenCode/Pi session id — became eligible for
LRU eviction by _prune_durable_metadata, which spares "error" but reaps
"closed". After eviction, same-session recovery has nothing to resume and
every interruption looks like "no artifact".

This suite pins the contract from three sides:
1. stop on an interrupted session preserves the error/resume semantics in
   the durable record (no closed-laundering).
2. The prune then refuses to evict that record under churn (with PR #533's
   protection active on the same file).
3. resume on the preserved record reopens the exact native session id.
"""

from __future__ import annotations

import json
import time

import pytest

import tools.delegate_session_tool as ds
from agent.delegate_health import reset_delegate_health_ledger

from tests.tools.test_delegate_session_tool import FakePiClient, Parent, payload


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
    FakePiClient.instances.clear()
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


def _durable_record(sid: str) -> dict | None:
    return ds._load_metadata(sid)


def _set_status_error(sid: str, *, error: str = "opencode delegate process exited with code 137") -> None:
    with ds._SESSION_LOCK:
        record = ds._SESSIONS[sid]
        record["status"] = "error"
        record["error"] = error
        record["updated_at"] = time.time()
    ds._persist_metadata(record)


def test_stop_on_interrupted_session_keeps_resumable_error_status():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    first_client = FakePiClient.instances[-1]
    _set_status_error(sid)

    stopped = payload(ds.delegate_session(action="stop", session_id=sid, parent_agent=parent))

    assert stopped["closed"] is True
    assert first_client.is_closed is True
    durable = _durable_record(sid)
    assert durable is not None, "durable identity must survive stop"
    assert durable.get("status") == "error", (
        "stop laundered an interrupted session to closed; the record becomes "
        "evictable and same-session recovery loses the native id mapping"
    )
    assert durable.get("native_session_id") == first_client.session_id


def test_interrupted_record_survives_prune_churn_after_stop():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    native = FakePiClient.instances[-1].session_id
    _set_status_error(sid)
    payload(ds.delegate_session(action="stop", session_id=sid, parent_agent=parent))

    # Heavy churn from unrelated terminal sessions must not evict the
    # interrupted record (500-cap LRU prune).
    ds._prune_durable_metadata(ds._session_store_root())
    record_path = ds._metadata_path(sid)
    assert record_path.exists(), "prune evicted the interrupted-session record"
    kept = json.loads(record_path.read_text())
    assert kept.get("status") == "error"
    assert kept.get("native_session_id") == native


def test_resume_after_stop_reopens_exact_native_session():
    parent = Parent()
    started = payload(ds.delegate_session(action="start", parent_agent=parent))
    sid = started["session_id"]
    first_client = FakePiClient.instances[-1]
    _set_status_error(sid)
    payload(ds.delegate_session(action="stop", session_id=sid, parent_agent=parent))

    # Registry loss (gateway restart) between interruption and recovery.
    with ds._SESSION_LOCK:
        ds._SESSIONS.pop(sid, None)

    resumed = payload(ds.delegate_session(action="resume", session_id=sid, parent_agent=parent))
    assert resumed["success"] is True
    assert resumed["session_id"] == sid
    reopened = FakePiClient.instances[-1]
    assert reopened is not first_client
    assert reopened.session_id == first_client.session_id, (
        "resume must reopen the exact interrupted native session id, not mint a new one"
    )

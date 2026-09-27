"""Delete/prune paths must stay idempotent under a write retry.

``SessionDB._execute_write`` replays the WHOLE callback after a rollback
(``SessionCompressionInProgressError`` / locked / busy are transient), so the
ids a delete removed may only leave the callback through its RETURN value.
The pre-fix shape kept ``removed_ids`` in the enclosing frame and
``extend()``-ed it inside ``_do``: a retried attempt replayed the extend, then
drove ``_remove_session_files`` for stale ids — transcript files deleted for
sessions a later attempt no longer selected. This suite fails that shape by
asserting each removed session's files are swept exactly once even when the
write retries (rm-033; boundary-ledger I55 lineage — upstream carries the
identical bug, so the regression lives here).
"""

from __future__ import annotations

import uuid

import pytest

from hermes_state import SessionDB
from hermes_state_errors import SessionCompressionInProgressError


@pytest.fixture
def db(tmp_path):
    handle = SessionDB(db_path=tmp_path / "state.db")
    yield handle
    handle.close()


def _retry_once_then_succeed(db, monkeypatch):
    """Make the FIRST _do attempt fail after it already did its row work (the
    last statement every delete callback runs is _delete_unreferenced_system_prompts),
    then let the replay succeed. Returns (swept_ids, attempts) where swept_ids collects
    every id whose files were swept."""
    real = db._delete_unreferenced_system_prompts
    calls = {"n": 0}

    def flaky(conn):
        calls["n"] += 1
        if calls["n"] == 1:
            raise SessionCompressionInProgressError("simulated mid-write compression lease")
        return real(conn)

    monkeypatch.setattr(db, "_delete_unreferenced_system_prompts", flaky)
    swept: list = []
    monkeypatch.setattr(db, "_remove_session_files", lambda sessions_dir, sid: swept.append(sid))
    return swept, calls


def _seed(db, n, with_message=True, ended=False):
    sids = []
    for _ in range(n):
        sid = str(uuid.uuid4())
        db.create_session(session_id=sid, source="cli")
        if with_message:
            db.append_message(sid, role="user", content="hello")
        if ended:
            db.end_session(sid, end_reason="test")
        sids.append(sid)
    return sids


def _seed_delegate_child(db, parent_sid):
    """A sub-agent child the delete paths cascade (model_config._delegate_from marker)."""
    child_sid = str(uuid.uuid4())
    db.create_session(
        session_id=child_sid, source="cli", parent_session_id=parent_sid,
        model_config={"_delegate_from": parent_sid},
    )
    db.append_message(child_sid, role="assistant", content="delegated")
    return child_sid


class TestDeleteSession:
    def test_retried_write_sweeps_files_exactly_once(self, db, monkeypatch):
        sid = _seed(db, 1)[0]
        child = _seed_delegate_child(db, sid)  # cascades with the parent
        swept, attempts = _retry_once_then_succeed(db, monkeypatch)
        assert db.delete_session(sid) is True
        assert attempts["n"] == 2  # the retry really happened
        assert sorted(swept) == sorted([sid, child])  # pre-fix: child swept twice


class TestDeleteSessions:
    def test_retried_write_sweeps_each_file_exactly_once(self, db, monkeypatch):
        sids = _seed(db, 1)
        child = _seed_delegate_child(db, sids[0])
        swept, attempts = _retry_once_then_succeed(db, monkeypatch)
        assert db.delete_sessions(sids) == 1
        assert attempts["n"] == 2
        assert sorted(swept) == sorted([sids[0], child])  # pre-fix: child swept twice
        assert len(swept) == len(set(swept))


class TestDeleteEmptySessions:
    def test_retried_write_sweeps_each_file_exactly_once(self, db, monkeypatch):
        sids = _seed(db, 2, with_message=False, ended=True)
        swept, attempts = _retry_once_then_succeed(db, monkeypatch)
        assert db.delete_empty_sessions() == 2
        assert attempts["n"] == 2
        assert sorted(swept) == sorted(sids)  # pre-fix: every id twice
        assert len(swept) == len(set(swept))


class TestPruneSessions:
    def test_retried_write_sweeps_each_file_exactly_once(self, db, monkeypatch, tmp_path):
        sids = _seed(db, 2, ended=True)  # prune candidates: ended, non-archived, unpinned
        swept, attempts = _retry_once_then_succeed(db, monkeypatch)
        assert db.prune_sessions(older_than_days=0, sessions_dir=tmp_path) == 2
        assert attempts["n"] == 2
        assert sorted(swept) == sorted(sids)  # pre-fix: every id twice
        assert len(swept) == len(set(swept))

    def test_prune_no_match_does_not_sweep(self, db, monkeypatch, tmp_path):
        _seed(db, 1, ended=True)
        swept, _attempts = _retry_once_then_succeed(db, monkeypatch)
        # Age window excludes everything: nothing selected, nothing swept.
        assert db.prune_sessions(older_than_days=3650, sessions_dir=tmp_path) == 0
        assert swept == []

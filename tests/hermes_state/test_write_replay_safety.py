"""Write-replay safety for the session-maintenance delete paths.

``SessionDB._execute_write`` retries the WHOLE callback under lock contention
(its docstring contract: ``fn must stay idempotent under retry``).  A callback
that mutates accumulator state OUTSIDE itself — e.g. extending a
``removed_ids`` list built before ``_execute_write`` — double-applies when the
failed attempt's outer mutations survive its rollback.  These tests simulate
one documented replay (attempt runs, transaction rolls back, attempt runs
again on the restored state) and pin that transcript-file removal happens
exactly once per session id, and that the DB effect is unchanged.
"""

import time

import pytest

from hermes_state import SessionDB


@pytest.fixture
def db(tmp_path):
    return SessionDB(tmp_path / "state.db")


@pytest.fixture
def removed_files(db, monkeypatch):
    """Count transcript-file removals driven by the delete paths."""
    calls: list[str] = []
    monkeypatch.setattr(db, "_remove_session_files", lambda sessions_dir, sid: calls.append(sid))
    return calls


def _force_callback_replay(db, monkeypatch):
    """Make ``_execute_write`` replay its callback once.

    The first attempt runs inside the real transaction and is then rolled
    back — the DB state a production retry sees after a failed attempt.  The
    replay runs on that restored state and its result is the one committed.
    """
    real_execute_write = db._execute_write

    def replaying_execute_write(fn, **kwargs):
        def traced(conn):
            fn(conn)
            conn.rollback()
            return fn(conn)
        return real_execute_write(traced, **kwargs)

    monkeypatch.setattr(db, "_execute_write", replaying_execute_write)


def _backdate(db, session_id, days=100):
    db._conn.execute(
        "UPDATE sessions SET started_at = ? WHERE id = ?",
        (time.time() - days * 86400, session_id),
    )
    db._conn.commit()


def test_prune_sessions_replay_removes_each_transcript_once(db, tmp_path, monkeypatch, removed_files):
    db.create_session(session_id="old", source="cli")
    db.end_session("old", end_reason="done")
    _backdate(db, "old")

    _force_callback_replay(db, monkeypatch)
    assert db.prune_sessions(older_than_days=90, sessions_dir=tmp_path) == 1

    assert removed_files == ["old"]
    assert db.get_session("old") is None


def test_delete_session_replay_removes_each_transcript_once(db, tmp_path, monkeypatch, removed_files):
    db.create_session(session_id="victim", source="cli")

    _force_callback_replay(db, monkeypatch)
    assert db.delete_session("victim", sessions_dir=tmp_path) is True

    assert removed_files == ["victim"]
    assert db.get_session("victim") is None


def test_delete_sessions_replay_removes_each_transcript_once(db, tmp_path, monkeypatch, removed_files):
    for sid in ("a", "b"):
        db.create_session(session_id=sid, source="cli")

    _force_callback_replay(db, monkeypatch)
    assert db.delete_sessions(["a", "b"], sessions_dir=tmp_path) == 2

    assert sorted(removed_files) == ["a", "b"]
    assert db.get_session("a") is None and db.get_session("b") is None


def test_delete_empty_sessions_replay_removes_each_transcript_once(db, tmp_path, monkeypatch, removed_files):
    db.create_session(session_id="ghost", source="desktop")
    db.end_session("ghost", end_reason="tui_close")

    _force_callback_replay(db, monkeypatch)
    assert db.delete_empty_sessions(sessions_dir=tmp_path) == 1

    assert removed_files == ["ghost"]
    assert db.get_session("ghost") is None

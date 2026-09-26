"""``prune_sessions`` must stay idempotent under ``_execute_write`` retry.

``_execute_write`` retries the WHOLE callback on a locked/busy collision, and
its docstring makes that an explicit contract: *fn must stay idempotent under
retry*. ``prune_sessions`` used to accumulate the removed session ids in a
closure over a caller-owned list — a rolled-back first attempt still left its
ids in the list, so the replayed (committed) attempt appended them a second
time and ``_remove_session_files`` ran twice per session (and ran for ids a
failed attempt never removed, deleting transcript files of live sessions).

These tests simulate the production retry — callback runs, transaction rolls
back, callback replays and commits — with the seam the suite already uses
(intercepting ``_execute_write`` and delegating to the real one), against a
real SQLite file. The contract pinned: the ids reported to the file-removal
pass come from the committed attempt only, each exactly once.
"""

from __future__ import annotations

import time
from unittest.mock import patch

from hermes_state import SessionDB

DAY = 86400.0


def _insert_ended_old(db, session_id, *, age_days=120):
    row = {
        "id": session_id,
        "source": "telegram",
        "user_id": "user-1",
        "session_key": f"agent:main:telegram:dm:{session_id}",
        "chat_id": "chat-1",
        "chat_type": "dm",
        "started_at": time.time() - age_days * DAY,
        "ended_at": time.time() - (age_days - 1) * DAY,
        "message_count": 1,
        "tool_call_count": 0,
        "api_call_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "archived": 0,
        "pinned": 0,
    }
    cols = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    db._conn.execute(
        f"INSERT INTO sessions ({cols}) VALUES ({placeholders})", list(row.values())
    )
    db._conn.commit()
    return session_id


def test_prune_sessions_retry_does_not_duplicate_file_removals(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    _insert_ended_old(db, "old-a")
    _insert_ended_old(db, "old-b")

    removed_files: list[str] = []
    real_execute_write = SessionDB._execute_write

    def intercepted_execute_write(self, fn, patience_s=None):
        def retried(conn):
            fn(conn)          # attempt 1 — its transaction is rolled back below
            conn.rollback()   # the lock collision that triggers the retry
            return fn(conn)   # attempt 2 replays and commits
        return real_execute_write(self, retried, patience_s)

    with patch.object(SessionDB, "_execute_write", intercepted_execute_write), \
            patch.object(db, "_remove_session_files", side_effect=lambda d, sid: removed_files.append(sid)):
        count = db.prune_sessions(older_than_days=30, sessions_dir=tmp_path / "sessions")

    assert count == 2
    # Exactly the committed attempt's ids, each once — the rolled-back attempt's
    # closure accumulation (["old-a", "old-b", "old-a", "old-b"]) is the bug.
    assert sorted(removed_files) == ["old-a", "old-b"]
    assert len(removed_files) == 2


def test_prune_sessions_without_retry_removes_each_file_once(tmp_path):
    """Plain path (no collision): same contract, one attempt."""
    db = SessionDB(db_path=tmp_path / "state.db")
    _insert_ended_old(db, "solo")

    removed_files: list[str] = []
    with patch.object(db, "_remove_session_files", side_effect=lambda d, sid: removed_files.append(sid)):
        count = db.prune_sessions(older_than_days=30, sessions_dir=tmp_path / "sessions")

    assert count == 1
    assert removed_files == ["solo"]

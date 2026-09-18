"""Routing-neutral per-task ``owner`` field — behaviour contracts.

Covers the odd-numbered plan items (T1 schema/create-default/migration-backfill,
T3 model tools) of ``docs/kanban/task-owner-field-plan.md``:

- ``owner`` defaults to the creator at WRITE time (no read-path COALESCE),
  including decompose fan-out children (they are created, not routed);
- free text: stripped, ``""`` stored/read as NULL, never profile-validated;
- ``set_task_owner`` transfers under a live claim without touching any
  routing column (the deliberate contrast with ``assign_task``), records an
  ``owner_transferred`` event carrying ``{"from", "to"}``, and refuses only
  archived/unknown tasks;
- legacy DBs backfill ``owner = created_by`` exactly once on first column-add;
- ``kanban_create``/``kanban_show``/``kanban_list`` round-trip the field.

The CLI-verb and dashboard-REST rows of the plan's test matrix live with the
even-numbered surfaces (T2/T4) and are not asserted here.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    """Isolated HERMES_HOME with an empty kanban DB."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb._INITIALIZED_PATHS.clear()
    kb.init_db()
    return home


# ---------------------------------------------------------------------------
# create_task: write-time default + free-text canonicalization
# ---------------------------------------------------------------------------

def test_create_owner_defaults_to_creator(kanban_home):
    conn = kbc.connect()
    try:
        tid = kb.create_task(conn, title="defaults", assignee="worker", created_by="codeo1io")
        assert kb.get_task(conn, tid).owner == "codeo1io"
    finally:
        conn.close()


def test_decompose_fanout_children_default_owner_to_decomposer(kanban_home):
    """Decomposed children are CREATED, not routed — they take the same
    write-time creator default as every other creation path (review finding:
    the raw graph INSERT used to leave them owner-NULL)."""
    from hermes_cli.kanban_db_graph import decompose_triage_task

    conn = kbc.connect()
    try:
        root = kb.create_task(conn, title="root", triage=True, created_by="codeo1io")
        child_ids = decompose_triage_task(
            conn, root, root_assignee="default",
            children=[{"title": "a"}, {"title": "b"}], author="codeo1io",
        )
        assert child_ids and len(child_ids) == 2
        owners = {kb.get_task(conn, cid).owner for cid in child_ids}
        assert owners == {"codeo1io"}
        # The children are reachable through the owner filter like any task.
        listed = kb.list_tasks(conn, owner="codeo1io")
        assert set(t.id for t in listed) >= set(child_ids)
    finally:
        conn.close()


def test_create_explicit_owner_honored_verbatim(kanban_home):
    """Owner is free text, not a profile: casing kept, whitespace stripped."""
    conn = kbc.connect()
    try:
        tid = kb.create_task(
            conn, title="explicit", assignee="worker", created_by="codeo1io", owner="codeo1io"
        )
        assert kb.get_task(conn, tid).owner == "codeo1io"

        # Blank owner is "not set" — falls back to the creator, never "".
        blank = kb.create_task(conn, title="blank", assignee="worker", created_by="default", owner="   ")
        assert kb.get_task(conn, blank).owner == "default"
    finally:
        conn.close()


def test_owner_empty_string_reads_as_none(kanban_home):
    """The EMPTY-IS-NULL column contract: a legacy/raw "" row reads as None."""
    conn = kbc.connect()
    try:
        tid = kb.create_task(conn, title="raw", assignee="worker", created_by="codeo1io")
        conn.execute("UPDATE tasks SET owner = '' WHERE id = ?", (tid,))
        task = kb.get_task(conn, tid)
        assert task.owner is None
    finally:
        conn.close()


def test_create_event_payload_carries_created_owner(kanban_home):
    """The audit trail starts at creation: the 'created' event's ``owner``
    is the write-time default, matching the row (contract #2)."""
    conn = kbc.connect()
    try:
        tid = kb.create_task(conn, title="ev", assignee="worker", created_by="codeo1io")
        row = conn.execute(
            "SELECT payload FROM task_events WHERE task_id = ? AND kind = 'created'", (tid,)
        ).fetchone()
        payload = json.loads(row["payload"])
        assert payload["owner"] == "codeo1io"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# set_task_owner: transfer semantics + audit
# ---------------------------------------------------------------------------

def test_set_task_owner_unknown_id_returns_false(kanban_home):
    conn = kbc.connect()
    try:
        assert kb.set_task_owner(conn, "no-such-task", "voice") is False
    finally:
        conn.close()


def test_set_task_owner_transfers_and_audits(kanban_home):
    conn = kbc.connect()
    try:
        tid = kb.create_task(conn, title="t", assignee="worker", created_by="codeo1io")
        assert kb.set_task_owner(conn, tid, "voice") is True
        assert kb.get_task(conn, tid).owner == "voice"

        row = conn.execute(
            "SELECT kind, payload FROM task_events WHERE task_id = ? "
            "ORDER BY id DESC LIMIT 1", (tid,),
        ).fetchone()
        assert row["kind"] == "owner_transferred"
        assert json.loads(row["payload"]) == {"from": "codeo1io", "to": "voice"}

        # Clear ("" and None both mean "no owner").
        assert kb.set_task_owner(conn, tid, "") is True
        assert kb.get_task(conn, tid).owner is None
        row = conn.execute(
            "SELECT payload FROM task_events WHERE task_id = ? "
            "ORDER BY id DESC LIMIT 1", (tid,),
        ).fetchone()
        assert json.loads(row["payload"]) == {"from": "voice", "to": None}
    finally:
        conn.close()


def test_owner_transfer_is_routing_neutral_under_live_claim(kanban_home):
    """THE contract: a running, claimed task transfers owner while every
    routing/claim/failure column stays byte-identical — the exact opposite of
    ``assign_task``, which raises and resets ``consecutive_failures``."""
    conn = kbc.connect()
    try:
        tid = kb.create_task(conn, title="live", assignee="worker", created_by="codeo1io")
        conn.execute(
            "UPDATE tasks SET status = 'running', claim_lock = 'lk-1', "
            "claim_expires = 9999999999, consecutive_failures = 3, "
            "last_failure_error = 'boom', assignee = 'worker' WHERE id = ?", (tid,)
        )
        routing_cols = (
            "assignee", "status", "claim_lock", "claim_expires",
            "consecutive_failures", "last_failure_error",
        )
        before = conn.execute(
            f"SELECT {', '.join(routing_cols)} FROM tasks WHERE id = ?", (tid,)
        ).fetchone()

        assert kb.set_task_owner(conn, tid, "voice") is True

        after = conn.execute(
            f"SELECT {', '.join(routing_cols)} FROM tasks WHERE id = ?", (tid,)
        ).fetchone()
        assert tuple(before) == tuple(after)
        assert kb.get_task(conn, tid).owner == "voice"
    finally:
        conn.close()


def test_set_task_owner_refuses_archived(kanban_home):
    conn = kbc.connect()
    try:
        tid = kb.create_task(conn, title="done", assignee="worker", created_by="codeo1io")
        assert kb.archive_task(conn, tid) is True
        with pytest.raises(RuntimeError, match="archived"):
            kb.set_task_owner(conn, tid, "voice")
        assert kb.get_task(conn, tid).owner == "codeo1io"
    finally:
        conn.close()


def test_set_task_owner_fires_updated_observer_after_commit(kanban_home):
    """Contract #6: notify_task_updated fires with ("owner",) — field names only."""
    conn = kbc.connect()
    try:
        tid = kb.create_task(conn, title="obs", assignee="worker", created_by="codeo1io")
        seen: list[tuple[str, tuple[str, ...]]] = []
        real = kb.notify_task_updated

        def spy(c, task_id, changed_fields, **kw):
            seen.append((task_id, tuple(changed_fields)))
            return real(c, task_id, changed_fields, **kw)

        kb.notify_task_updated = spy
        try:
            kb.set_task_owner(conn, tid, "voice")
        finally:
            kb.notify_task_updated = real
        assert seen == [(tid, ("owner",))]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# list_tasks: owner filter (routing surfaces stay owner-blind; this is the
# one read surface that may consult owner — an explicit human filter)
# ---------------------------------------------------------------------------

def test_list_tasks_filters_by_owner(kanban_home):
    conn = kbc.connect()
    try:
        a = kb.create_task(conn, title="a", assignee="worker", created_by="codeo1io", owner="voice")
        b = kb.create_task(conn, title="b", assignee="worker", created_by="codeo1io", owner="default")
        c = kb.create_task(conn, title="c", assignee="worker", created_by="codeo1io")
        assert [t.id for t in kb.list_tasks(conn, owner="voice")] == [a]
        assert [t.id for t in kb.list_tasks(conn, owner="default")] == [b]
        # codeo1io owns her own unattributed card via the creator default.
        assert [t.id for t in kb.list_tasks(conn, owner="codeo1io")] == [c]
        assert kb.list_tasks(conn, owner="nobody") == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Migration: one-shot first-add backfill
# ---------------------------------------------------------------------------

LEGACY_TASKS_SQL = """
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT,
    assignee TEXT,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    created_by TEXT,
    created_at INTEGER NOT NULL,
    started_at INTEGER,
    completed_at INTEGER,
    workspace_kind TEXT NOT NULL DEFAULT 'scratch',
    workspace_path TEXT,
    claim_lock TEXT,
    claim_expires INTEGER
)
"""

LEGACY_EVENTS_SQL = """
CREATE TABLE task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT,
    created_at INTEGER NOT NULL
)
"""


def _legacy_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "legacy-kanban.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(LEGACY_TASKS_SQL)
    conn.execute(LEGACY_EVENTS_SQL)
    conn.execute(
        "INSERT INTO tasks (id, title, status, created_at, created_by) "
        "VALUES ('l1', 'attributed', 'ready', 1, 'legacy-owner')"
    )
    # Rows with no creator (NULL created_by) must backfill to NULL, not ''.
    conn.execute(
        "INSERT INTO tasks (id, title, status, created_at) "
        "VALUES ('l2', 'unattributed', 'ready', 1)"
    )
    conn.commit()
    conn.close()
    return db_path


def test_migration_backfills_owner_from_created_by(tmp_path):
    db_path = _legacy_db(tmp_path)
    with kbc.connect(db_path) as conn:
        assert "owner" in {
            row["name"] for row in conn.execute("PRAGMA table_info(tasks)")
        }
        rows = {r["id"]: r["owner"] for r in conn.execute("SELECT id, owner FROM tasks")}
        assert rows == {"l1": "legacy-owner", "l2": None}
        assert kb.get_task(conn, "l1").owner == "legacy-owner"


def test_migration_backfill_is_one_shot_cleared_owner_survives_reopen(tmp_path):
    """First-add guard: an owner cleared AFTER the migration must not be
    resurrected by the next open (an every-open UPDATE would do exactly that)."""
    db_path = _legacy_db(tmp_path)
    with kbc.connect(db_path) as conn:
        assert kb.set_task_owner(conn, "l1", None) is True
    with kbc.connect(db_path) as conn:
        rows = {r["id"]: r["owner"] for r in conn.execute("SELECT id, owner FROM tasks")}
        assert rows == {"l1": None, "l2": None}
        assert kb.get_task(conn, "l1").owner is None


# ---------------------------------------------------------------------------
# Model tools (T3): create param + read display
# ---------------------------------------------------------------------------

@pytest.fixture
def orchestrator_env(tmp_path, monkeypatch):
    """Isolated HERMES_HOME seen by the kanban model tools; creating profile 'orch'."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_PROFILE", "orch")
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.delenv("HERMES_SESSION_ID", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb._INITIALIZED_PATHS.clear()
    kb.init_db()
    return home


def test_kanban_create_owner_param_lands(orchestrator_env):
    from tools import kanban_tools as kt

    out = kt._handle_create({"title": "owned", "assignee": "worker", "owner": "voice"})
    d = json.loads(out)
    assert d["ok"] is True
    conn = kbc.connect()
    try:
        task = kb.get_task(conn, d["task_id"])
        assert task.owner == "voice"
        assert task.created_by == "orch"  # owner ≠ creator here by explicit choice
    finally:
        conn.close()

    # Omitted owner → creator default through the same tool path.
    out2 = kt._handle_create({"title": "defaulted", "assignee": "worker"})
    tid2 = json.loads(out2)["task_id"]
    conn = kbc.connect()
    try:
        assert kb.get_task(conn, tid2).owner == "orch"
    finally:
        conn.close()


def test_kanban_show_and_list_include_owner(orchestrator_env):
    from tools import kanban_tools as kt

    conn = kbc.connect()
    try:
        tid = kb.create_task(conn, title="shown", assignee="worker", created_by="orch", owner="voice")
    finally:
        conn.close()
    shown = json.loads(kt._handle_show({"task_id": tid}))
    assert shown["task"]["owner"] == "voice"

    listed = json.loads(kt._handle_list({}))
    entry = next(t for t in listed["tasks"] if t["id"] == tid)
    assert entry["owner"] == "voice"


def test_kanban_create_schema_declares_owner(orchestrator_env):
    """The param must be on the wire schema, or no model can ever send it."""
    from tools.kanban_tools_schemas import KANBAN_CREATE_SCHEMA

    assert "owner" in KANBAN_CREATE_SCHEMA["parameters"]["properties"]

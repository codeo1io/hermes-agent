"""Post-deploy owner reconciliation (G4) + ``effective_owner`` display (G3).

Two verified-remaining gaps of the owner feature (docs/kanban-owner.md §5):

- G3: read surfaces resolve ``effective_owner = owner ?? created_by ?? None``.
  Legacy/mixed-version rows written without the owner column display their
  creator; the stored value stays NULL (the "explicitly cleared" sentinel) and
  SQL stays COALESCE-free.
- G4: ``reconcile_task_owners`` re-points window rows (``owner IS NULL AND
  created_by IS NOT NULL``) at their creator, exactly once per board, guarded
  by ``PRAGMA user_version``. Dry-run reports the plan without writing. Every
  changed row gets an ``owner_reconciled`` audit event. Explicit CLI trigger
  only (``hermes kanban owner-reconcile [--apply]``) — the migration pass must
  NOT auto-run it, or the dry-run preview is consumed before anyone sees it.
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
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.delenv("HERMES_DELEGATED_CHILD_CONTEXT", raising=False)
    kb._INITIALIZED_PATHS.clear()
    kb.init_db()
    return home


def _user_version(conn) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _window_row(conn, task_id: str, creator: str | None) -> None:
    """Insert a row the way the pre-owner install did: no owner, raw SQL."""
    conn.execute(
        "INSERT INTO tasks (id, title, assignee, status, priority, created_at,"
        " workspace_kind, workspace_path, created_by)"
        " VALUES (?, 'window row', 'worker', 'todo', 0, 1, 'scratch', '/tmp/x', ?)",
        (task_id, creator),
    )
    conn.commit()


# --- G3: effective_owner -----------------------------------------------------


def test_effective_owner_falls_back_to_created_by(kanban_home):
    conn = kbc.connect()
    try:
        _window_row(conn, "w1", "window-creator")
        t = kb.get_task(conn, "w1")
        assert t.owner is None                      # stored value stays honest
        assert t.effective_owner == "window-creator"
    finally:
        conn.close()


def test_effective_owner_prefers_explicit_owner(kanban_home):
    conn = kbc.connect()
    try:
        tid = kb.create_task(conn, title="owned", assignee="w", created_by="codeo1io", owner="voice")
        assert kb.get_task(conn, tid).effective_owner == "voice"
    finally:
        conn.close()


def test_effective_owner_none_when_both_missing(kanban_home):
    conn = kbc.connect()
    try:
        _window_row(conn, "n1", None)
        t = kb.get_task(conn, "n1")
        assert t.owner is None
        assert t.effective_owner is None
    finally:
        conn.close()


def test_migration_pass_does_not_auto_reconcile(kanban_home):
    """The init/migration pass must leave the gate alone: reconciliation is an
    explicit, human-previewed step (dry-run must see the live board state)."""
    conn = kbc.connect()
    try:
        _window_row(conn, "w1", "window-creator")
        conn.close()
        kb._INITIALIZED_PATHS.clear()
        kb.init_db()                                # forced migration pass
        conn = kbc.connect()
        assert _user_version(conn) == 0
        assert kb.get_task(conn, "w1").owner is None
    finally:
        conn.close()


# --- G4: reconcile_task_owners ----------------------------------------------


def test_reconcile_repoints_window_rows_and_sets_gate(kanban_home):
    conn = kbc.connect()
    try:
        _window_row(conn, "w1", "window-creator")
        _window_row(conn, "w2", "other-creator")
        report = kb.reconcile_task_owners(conn)
        assert report["ran"] is True and report["dry_run"] is False
        assert report["already_reconciled"] is False
        assert report["changed"] == 2
        assert {(c["id"], c["to"]) for c in report["changes"]} == {
            ("w1", "window-creator"), ("w2", "other-creator")}
        assert kb.get_task(conn, "w1").owner == "window-creator"
        assert _user_version(conn) == kb.OWNER_RECONCILED_USER_VERSION
        events = [e.kind for e in kb.list_events(conn, "w1")]
        assert "owner_reconciled" in events         # audit trail
    finally:
        conn.close()


def test_reconcile_dry_run_writes_nothing_but_reports_plan(kanban_home):
    conn = kbc.connect()
    try:
        _window_row(conn, "w1", "window-creator")
        report = kb.reconcile_task_owners(conn, dry_run=True)
        assert report["ran"] is False and report["dry_run"] is True
        assert report["candidates"] == 1
        assert report["changes"] == [{"id": "w1", "from": None, "to": "window-creator"}]
        assert report["changed"] == 0
        assert kb.get_task(conn, "w1").owner is None    # nothing written
        assert _user_version(conn) == 0                 # gate untouched
    finally:
        conn.close()


def test_reconcile_is_one_shot_gate_blocks_second_run(kanban_home):
    conn = kbc.connect()
    try:
        _window_row(conn, "w1", "window-creator")
        first = kb.reconcile_task_owners(conn)
        assert first["changed"] == 1
        # A fresh window row must NOT be swept by a second call: the gate says
        # reconciliation already happened, and post-gate rows are the deploy's
        # normal owner-writing regime.
        _window_row(conn, "w3", "post-deploy-creator")
        second = kb.reconcile_task_owners(conn)
        assert second["ran"] is False and second["already_reconciled"] is True
        assert second["candidates"] == 0
        assert kb.get_task(conn, "w3").owner is None
    finally:
        conn.close()


def test_reconcile_idempotent_without_gate(kanban_home):
    """Even with the gate forcibly removed, the UPDATE is a fixed point."""
    conn = kbc.connect()
    try:
        _window_row(conn, "w1", "window-creator")
        kb.reconcile_task_owners(conn)
        conn.execute("PRAGMA user_version = 0")     # simulate gate loss
        report = kb.reconcile_task_owners(conn)
        assert report["candidates"] == 0
        assert report["changed"] == 0
        assert _user_version(conn) == kb.OWNER_RECONCILED_USER_VERSION
    finally:
        conn.close()


def test_reconcile_skips_null_creator_rows(kanban_home):
    conn = kbc.connect()
    try:
        _window_row(conn, "n1", None)
        report = kb.reconcile_task_owners(conn)
        assert report["candidates"] == 0 and report["changed"] == 0
        assert kb.get_task(conn, "n1").owner is None
        assert kb.get_task(conn, "n1").effective_owner is None
    finally:
        conn.close()


def test_reconcile_clear_after_reconcile_survives_reopen(kanban_home):
    """An explicit clear AFTER reconciliation is never resurrected — the gate,
    not the UPDATE's WHERE clause alone, is the one-shot guarantee."""
    conn = kbc.connect()
    try:
        _window_row(conn, "w1", "window-creator")
        kb.reconcile_task_owners(conn)
        assert kb.set_task_owner(conn, "w1", None) is True
        assert kb.get_task(conn, "w1").owner is None
        conn.close()
        kb._INITIALIZED_PATHS.clear()
        kb.init_db()
        conn = kbc.connect()
        assert kb.get_task(conn, "w1").owner is None
    finally:
        conn.close()


# --- CLI verb -----------------------------------------------------------------


def test_cli_owner_reconcile_dry_run_apply_and_gate(kanban_home, capsys):
    import argparse

    from hermes_cli.kanban import kanban_command
    from hermes_cli.kanban_parser import build_parser

    parser = argparse.ArgumentParser()
    build_parser(parser.add_subparsers())

    def run(*argv: str):
        capsys.readouterr()
        rc = kanban_command(parser.parse_args(("kanban",) + argv))
        captured = capsys.readouterr()
        return rc, captured.out, captured.err

    conn = kbc.connect()
    _window_row(conn, "w1", "window-creator")
    conn.close()

    rc, out, err = run("owner-reconcile", "--json")
    assert rc == 0, err
    plan = json.loads(out)
    assert plan["dry_run"] is True and plan["candidates"] == 1
    assert plan["changes"] == [{"id": "w1", "from": None, "to": "window-creator"}]

    conn = kbc.connect()
    assert kb.get_task(conn, "w1").owner is None    # dry run wrote nothing
    conn.close()

    rc, out, err = run("owner-reconcile", "--apply")
    assert rc == 0, err
    assert "repointed 1 task(s)" in out

    rc, out, err = run("owner-reconcile")
    assert rc == 0, err
    assert "already ran" in out

    conn = kbc.connect()
    assert kb.get_task(conn, "w1").owner == "window-creator"
    assert _user_version(conn) == kb.OWNER_RECONCILED_USER_VERSION
    conn.close()


def test_cli_show_and_list_display_effective_owner(kanban_home, capsys):
    import argparse

    from hermes_cli.kanban import kanban_command
    from hermes_cli.kanban_parser import build_parser

    parser = argparse.ArgumentParser()
    build_parser(parser.add_subparsers())

    def run(*argv: str):
        capsys.readouterr()
        rc = kanban_command(parser.parse_args(("kanban",) + argv))
        captured = capsys.readouterr()
        return rc, captured.out, captured.err

    conn = kbc.connect()
    _window_row(conn, "w1", "window-creator")
    conn.close()

    rc, out, err = run("show", "w1")
    assert rc == 0, err
    assert "owner:" in out
    assert "window-creator" in out                  # creator displayed, not "-"

    rc, out, err = run("list")
    assert rc == 0, err
    assert "window-creator" in out

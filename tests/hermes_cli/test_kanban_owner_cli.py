"""CLI surface of the routing-neutral per-task owner field.

Covers `hermes kanban owner <id> <name|none>`, `create --owner`, `list --owner`,
the `show`/`list`/`--json` display, the delegated-child denial gate for the new
verb, and the archived refusal path. DB-layer contracts (default-to-creator,
transfer audit, routing-neutrality under a live claim, migration backfill) live
in ``test_kanban_owner.py``; the dashboard REST surface in
``tests/plugins/test_kanban_owner_api.py``.
"""

from __future__ import annotations

import argparse
import json

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli.kanban import kanban_command
from hermes_cli.kanban_parser import build_parser
from tests.kanban_pin_testutils import pin_kanban_db


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    pin_kanban_db(monkeypatch, tmp_path)
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.delenv("HERMES_DELEGATED_CHILD_CONTEXT", raising=False)
    kb.init_db()
    return home


@pytest.fixture
def run(kanban_home, capsys):
    parser = argparse.ArgumentParser()
    build_parser(parser.add_subparsers())

    def _run(*argv: str) -> tuple[int, str, str]:
        capsys.readouterr()
        rc = kanban_command(parser.parse_args(("kanban",) + argv))
        captured = capsys.readouterr()
        return rc, captured.out, captured.err

    return _run


def _create(run, *extra: str) -> str:
    rc, out, err = run("create", "probe task", "--json", *extra)
    assert rc == 0, err
    return json.loads(out)["id"]


# --- create -----------------------------------------------------------------


def test_create_owner_flag_stamps_the_card(run, kanban_home):
    with kbc.connect_closing() as conn:
        assert kb.get_task(conn, _create(run, "--owner", "codeo1io")).owner == "codeo1io"
        # Omitted → the creator default (CLI stamps created_by="user").
        assert kb.get_task(conn, _create(run)).owner == "user"


def test_create_json_output_includes_owner(run):
    rc, out, err = run("create", "probe task", "--owner", "codeo1io", "--json")
    assert rc == 0, err
    assert json.loads(out)["owner"] == "codeo1io"


# --- show / list display ------------------------------------------------------


def test_show_prints_the_owner_field(run):
    tid = _create(run, "--owner", "codeo1io")
    rc, out, err = run("show", tid)
    assert rc == 0, err
    assert "owner" in out
    assert "codeo1io" in out


def test_list_line_shows_owner_and_json_has_the_key(run):
    _create(run, "--owner", "codeo1io")
    rc, out, err = run("list")
    assert rc == 0, err
    assert "codeo1io" in out
    rc, out, err = run("list", "--json")
    assert rc == 0, err
    tasks = json.loads(out)
    assert tasks and all("owner" in t for t in tasks)
    assert any(t["owner"] == "codeo1io" for t in tasks)


def test_list_owner_flag_filters(run):
    tid_a = _create(run, "--owner", "codeo1io")
    _create(run, "--owner", "voice")
    rc, out, err = run("list", "--owner", "codeo1io", "--json")
    assert rc == 0, err
    listed = json.loads(out)
    assert [t["id"] for t in listed] == [tid_a]


# --- the owner verb -----------------------------------------------------------


def test_owner_verb_transfers_and_clears(run):
    tid = _create(run, "--owner", "codeo1io")
    rc, out, err = run("owner", tid, "voice")
    assert rc == 0, err
    assert "voice" in out
    with kbc.connect_closing() as conn:
        assert kb.get_task(conn, tid).owner == "voice"

    rc, out, err = run("owner", tid, "none")
    assert rc == 0, err
    assert "(none)" in out
    with kbc.connect_closing() as conn:
        assert kb.get_task(conn, tid).owner is None


def test_owner_verb_unknown_task_fails(run):
    rc, out, err = run("owner", "t_missing", "voice")
    assert rc == 1
    assert "no such task" in err


def test_owner_verb_refuses_archived_tasks(run):
    tid = _create(run, "--owner", "codeo1io")
    with kbc.connect_closing() as conn:
        assert kb.archive_task(conn, tid)
    rc, out, err = run("owner", tid, "voice")
    assert rc == 1
    assert "archived" in err


def test_show_renders_the_transfer_audit_event(run):
    tid = _create(run, "--owner", "codeo1io")
    assert run("owner", tid, "voice")[0] == 0
    rc, out, err = run("show", tid)
    assert rc == 0, err
    # The current owner and the from/to audit trail are both visible.
    assert "owner_transferred" in out
    assert "voice" in out


# --- delegated-child denial gate ----------------------------------------------


def test_delegated_child_cannot_use_the_owner_verb(run, monkeypatch):
    tid = _create(run, "--owner", "codeo1io")
    monkeypatch.setenv("HERMES_DELEGATED_CHILD_CONTEXT", "1")
    rc, out, err = run("owner", tid, "voice")
    assert rc == 1
    assert "delegate_task child contexts cannot mutate Kanban tasks via the CLI" in err
    with kbc.connect_closing() as conn:
        assert kb.get_task(conn, tid).owner == "codeo1io"


# --- roster validation (OWNERS.md v2 §0) --------------------------------------


def test_create_rejects_owner_outside_roster(run):
    rc, out, err = run("create", "probe task", "--owner", "alice")
    assert rc == 1
    assert "invalid owner 'alice'" in err
    assert "must be one of default, voice, codeo1io" in err
    with kbc.connect_closing() as conn:
        assert kb.list_tasks(conn) == []


def test_owner_verb_rejects_owner_outside_roster_and_keeps_old(run):
    tid = _create(run, "--owner", "codeo1io")
    rc, out, err = run("owner", tid, "ops")
    assert rc == 1
    assert "invalid owner 'ops'" in err
    with kbc.connect_closing() as conn:
        assert kb.get_task(conn, tid).owner == "codeo1io"
        kinds = [e.kind for e in kb.list_events(conn, tid)]
        assert "owner_transferred" not in kinds


def test_roster_override_admits_new_names(run, monkeypatch):
    monkeypatch.setenv("HERMES_OWNER_ROSTER", "default, platform-team")
    tid = _create(run)
    rc, out, err = run("owner", tid, "platform-team")
    assert rc == 0, err
    with kbc.connect_closing() as conn:
        assert kb.get_task(conn, tid).owner == "platform-team"


# --- owner-audit --------------------------------------------------------------


def test_owner_audit_clean_board_exits_zero(run):
    _create(run, "--owner", "default", "--assignee", "default")
    _create(run, "--owner", "voice", "--assignee", "voice")
    rc, out, err = run("owner-audit")
    assert rc == 0, err
    assert "OK: no unowned or invalid-owner open cards" in out
    rc, out, err = run("owner-audit", "--json")
    assert rc == 0, err
    report = json.loads(out)
    assert report["counts"] == {"unowned": 0, "invalid": 0, "divergence": 0}
    assert report["open_cards"] == 2
    assert report["issues"] == []


def test_owner_audit_exits_one_and_lists_each_issue_class(run):
    bad = _create(run, "--owner", "default", "--assignee", "default")
    ghost = _create(run, "--owner", "default", "--assignee", "default")
    with kbc.connect_closing() as conn:
        # Legacy pre-validation row (raw SQL bypasses the API guard)…
        conn.execute("UPDATE tasks SET owner = 'alice', assignee = 'coder' WHERE id = ?", (bad,))
        # …and an unowned row: no owner AND no created_by fallback.
        conn.execute("UPDATE tasks SET owner = NULL, created_by = NULL WHERE id = ?", (ghost,))
        conn.commit()
    rc, out, err = run("owner-audit")
    assert rc == 1
    assert f"invalid: {bad}" in out
    assert f"unowned: {ghost}" in out
    rc, out, err = run("owner-audit", "--json")
    assert rc == 1
    report = json.loads(out)
    assert report["counts"] == {"unowned": 1, "invalid": 1, "divergence": 1}
    assert report["unowned"] == [ghost]
    assert report["invalid"] == [{"id": bad, "owner": "alice"}]
    # owner 'alice' != assignee 'coder' on an open card — the §3 invariant flag.
    assert report["divergence"] == [{"id": bad, "owner": "alice", "assignee": "coder"}]


def test_owner_audit_honors_roster_override(run, monkeypatch):
    tid = _create(run, "--owner", "codeo1io", "--assignee", "codeo1io")
    monkeypatch.setenv("HERMES_OWNER_ROSTER", "default, platform-team")
    rc, out, err = run("owner-audit", "--json")
    assert rc == 1  # codeo1io is off the overridden roster
    report = json.loads(out)
    assert report["counts"]["invalid"] == 1
    assert report["invalid"] == [{"id": tid, "owner": "codeo1io"}]

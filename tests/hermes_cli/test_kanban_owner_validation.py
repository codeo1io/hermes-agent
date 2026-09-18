"""Owner roster validation + board audit (OWNERS.md v2 policy enforcement).

Covers the enforcement layer added on top of the routing-neutral owner field:

- ``validate_owner`` / ``_owner_or_none``: explicit owner values must be in
  the roster of record; blank/None falls through to the write-time
  ``owner = created_by`` default and never raises;
- ``create_task(owner=...)`` / ``set_task_owner`` reject unknown names with
  a clear roster error, on both create and transfer paths;
- ``audit_task_owners``: read-only, repeatable audit classifying open cards
  as unowned / invalid-owner / owner-vs-assignee divergence (OWNERS.md v2
  §3 invariant), with terminal cards exempt;
- ``HERMES_OWNER_ROSTER`` override for roster growth without code change.
"""

from __future__ import annotations

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_owner as ko
from tests.kanban_pin_testutils import pin_kanban_db


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    """Hermetic board via the sanctioned ``HERMES_KANBAN_DB`` pin.

    Not the old ``HERMES_HOME``/``Path.home`` dance: on the self-hosted runner
    ``tmp_path`` itself lands under the real kanban root, and a worker-context
    ``HERMES_KANBAN_DB`` pin (what the dispatcher injects) would otherwise leak
    the live board into ``kanban_db_path()`` resolution. See
    ``tests/kanban_pin_testutils.py`` (PR #15 CI fix 736da27312).
    """
    pin = pin_kanban_db(monkeypatch, tmp_path, label="owner-validation")
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.delenv("HERMES_DELEGATED_CHILD_CONTEXT", raising=False)
    kb._INITIALIZED_PATHS.clear()
    kb.init_db()
    return pin


@pytest.fixture
def conn(kanban_home):
    with kbc.connect_closing() as conn:
        yield conn


# ---------------------------------------------------------------------------
# validate_owner: roster check, blank pass-through, override
# ---------------------------------------------------------------------------

def test_validate_owner_accepts_roster_names():
    assert ko.validate_owner("default") == "default"
    assert ko.validate_owner("voice") == "voice"
    assert ko.validate_owner("codeo1io") == "codeo1io"
    assert ko.validate_owner("  default  ") == "default"


def test_validate_owner_blank_is_none_not_error():
    assert ko.validate_owner(None) is None
    assert ko.validate_owner("") is None
    assert ko.validate_owner("   ") is None


def test_validate_owner_rejects_unknown_with_roster_error():
    with pytest.raises(ValueError, match="invalid owner 'coder'"):
        ko.validate_owner("coder")
    with pytest.raises(ValueError, match=r"must be one of default, voice, codeo1io"):
        ko.validate_owner("alice")


def test_validate_owner_honors_roster_override(monkeypatch):
    monkeypatch.setenv("HERMES_OWNER_ROSTER", "default, platform-team")
    assert ko.validate_owner("platform-team") == "platform-team"
    with pytest.raises(ValueError, match="invalid owner 'voice'"):
        ko.validate_owner("voice")


# ---------------------------------------------------------------------------
# create_task: default/fallback unaffected; invalid explicit owner rejected
# ---------------------------------------------------------------------------

def test_create_owner_defaults_to_creator_when_blank(kanban_home, conn):
    tid = kb.create_task(conn, title="t", assignee="default",
                         created_by="default", owner=None)
    assert kb.get_task(conn, tid).owner == "default"
    tid2 = kb.create_task(conn, title="t2", assignee="default",
                          created_by="default", owner="   ")
    assert kb.get_task(conn, tid2).owner == "default"


def test_create_rejects_owner_outside_roster(kanban_home, conn):
    with pytest.raises(ValueError, match="invalid owner 'alice'"):
        kb.create_task(conn, title="t", assignee="default",
                       created_by="default", owner="alice")


def test_create_rejection_leaves_no_row_and_no_event(kanban_home, conn):
    with pytest.raises(ValueError):
        kb.create_task(conn, title="ghost", assignee="default",
                       created_by="default", owner="ops")
    assert kb.list_tasks(conn, owner=None) == []


# ---------------------------------------------------------------------------
# set_task_owner: valid transfer ok; invalid transfer rejected, old owner kept
# ---------------------------------------------------------------------------

def test_set_task_owner_accepts_roster_name(kanban_home, conn):
    tid = kb.create_task(conn, title="t", assignee="default", created_by="default")
    assert kb.set_task_owner(conn, tid, "codeo1io") is True
    assert kb.get_task(conn, tid).owner == "codeo1io"


def test_set_task_owner_rejects_invalid_and_keeps_old(kanban_home, conn):
    tid = kb.create_task(conn, title="t", assignee="default", created_by="default")
    with pytest.raises(ValueError, match="invalid owner 'zoe'"):
        kb.set_task_owner(conn, tid, "zoe")
    assert kb.get_task(conn, tid).owner == "default"
    kinds = [e.kind for e in kb.list_events(conn, tid)]
    assert "owner_transferred" not in kinds


def test_set_task_owner_clear_still_allowed(kanban_home, conn):
    tid = kb.create_task(conn, title="t", assignee="default", created_by="default")
    assert kb.set_task_owner(conn, tid, None) is True
    assert kb.get_task(conn, tid).owner is None


# ---------------------------------------------------------------------------
# audit_task_owners: classification + open/terminal split
# ---------------------------------------------------------------------------

def _seed_board(conn):
    owned = kb.create_task(conn, title="owned", assignee="default",
                           created_by="default")
    fallback = kb.create_task(conn, title="fallback", assignee="voice",
                              created_by="voice")  # explicit clear -> created_by
    divergent = kb.create_task(conn, title="divergent", assignee="voice",
                               created_by="default")
    kb.set_task_owner(conn, divergent, "codeo1io")
    return owned, fallback, divergent


def test_audit_clean_board_is_zero_counts(kanban_home, conn):
    _seed_board(conn)
    report = ko.audit_task_owners(conn)
    assert report["open_cards"] == 3
    assert report["counts"] == {"unowned": 0, "invalid": 0, "divergence": 1}
    assert [i["kind"] for i in report["issues"]] == ["divergence"]


def test_audit_unowned_card_no_owner_no_creator(kanban_home, conn):
    _seed_board(conn)
    conn.execute(
        "UPDATE tasks SET owner = NULL, created_by = NULL WHERE title = 'fallback'"
    )
    conn.commit()
    report = ko.audit_task_owners(conn)
    assert report["counts"]["unowned"] == 1
    unowned_id = report["unowned"][0]
    assert any(i["id"] == unowned_id and i["kind"] == "unowned"
               for i in report["issues"])


def test_audit_invalid_owner_flagged(kanban_home, conn):
    _seed_board(conn)
    # Simulate a pre-validation row (raw SQL, bypassing the API guard).
    conn.execute("UPDATE tasks SET owner = 'alice' WHERE title = 'owned'")
    conn.commit()
    report = ko.audit_task_owners(conn)
    assert report["counts"]["invalid"] == 1
    assert report["invalid"][0]["owner"] == "alice"


def test_audit_divergence_invariant_owner_equals_assignee(kanban_home, conn):
    """OWNERS.md v2 §3: owner == assignee on open cards; divergence is flagged."""
    _seed_board(conn)
    report = ko.audit_task_owners(conn)
    div = report["divergence"]
    assert len(div) == 1 and div[0]["id"]  # the codeo1io-owned card
    # Convergence heals it: routing catches up to accountability.
    kb.assign_task(conn, div[0]["id"], "codeo1io")
    report2 = ko.audit_task_owners(conn)
    assert report2["counts"]["divergence"] == 0


def test_audit_ignores_terminal_cards(kanban_home, conn):
    _seed_board(conn)
    tid = kb.create_task(conn, title="old", assignee="default", created_by="default")
    conn.execute("UPDATE tasks SET status = 'done', owner = 'old-owner' WHERE id = ?", (tid,))
    conn.commit()
    report = ko.audit_task_owners(conn)
    assert tid not in [i["id"] for i in report["issues"]]


def test_audit_covers_triage_cards(kanban_home, conn):
    """Regression: triage is a live pre-work status — unowned and off-roster
    owners in triage are findings the audit must report, not skip."""
    _seed_board(conn)
    t_unowned = kb.create_task(conn, title="awaiting flesh-out",
                               assignee="default", created_by="default",
                               triage=True)
    t_invalid = kb.create_task(conn, title="bad owner in triage",
                               assignee="default", created_by="default",
                               triage=True)
    conn.execute("UPDATE tasks SET owner = NULL, created_by = NULL WHERE id = ?",
                 (t_unowned,))
    conn.execute("UPDATE tasks SET owner = 'haxor' WHERE id = ?", (t_invalid,))
    conn.commit()

    report = ko.audit_task_owners(conn)
    ids = {i["id"]: i["kind"] for i in report["issues"]}
    assert ids.get(t_unowned) == "unowned"
    assert ids.get(t_invalid) == "invalid"
    assert report["counts"]["unowned"] == 1
    assert report["counts"]["invalid"] == 1
    assert t_unowned in report["unowned"]
    assert {"id": t_invalid, "owner": "haxor"} in report["invalid"]


def test_audit_is_repeatable_and_read_only(kanban_home, conn):
    _seed_board(conn)
    before = conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0]
    r1 = ko.audit_task_owners(conn)
    r2 = ko.audit_task_owners(conn)
    after = conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0]
    assert r1 == r2
    assert before == after  # no audit events, no writes


def test_audit_empty_board_is_clean(kanban_home, conn):
    """Zero open cards: zero counts, exit-healthy — no division-by-board errors."""
    report = ko.audit_task_owners(conn)
    assert report["open_cards"] == 0
    assert report["counts"] == {"unowned": 0, "invalid": 0, "divergence": 0}
    assert report["issues"] == []

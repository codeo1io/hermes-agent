"""The review-rework round cap (``kanban.max_review_rounds``): a non-converging card
must stop at the cap instead of cycling ``changes_requested`` forever (upstream
#149149 spec — the 5-executor-session incident). Every review round is a clean
lifecycle exit, so no existing counter (``failure_limit``, protocol violations,
block recurrence) ever trips on it.

Contract:

* at the cap, the next ``changes_requested`` verdict is still recorded (runs and
  events are never erased) but grants NO rework: the card blocks ``needs_input``
  with one ``rework_cap_reached`` event carrying the counted run ids;
* an ordinary unblock does NOT grant more rounds; only ``unblock(reset_rework=True)``
  does, recorded as a ``rework_reset`` baseline event (an offset, not a delete);
* ``0`` disables the cap entirely.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc


@pytest.fixture
def kanban_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated HERMES_HOME with an empty kanban DB."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


def _cap(monkeypatch: pytest.MonkeyPatch, value: int) -> None:
    from hermes_cli import config_effective

    monkeypatch.setattr(
        config_effective, "load_user_config_effective",
        lambda *a, **k: {"kanban": {"max_review_rounds": value}},
    )


def _review_round(conn, tid: str, reason: str = "fix"):
    """One full implementer->review->changes_requested round; returns request_changes' result."""
    claimed = kb.claim_task(conn, tid)
    kb.request_review(conn, tid, summary="ready for review", reviewer="reviewer",
                      expected_run_id=claimed.current_run_id)
    rclaim = kb.claim_review_task(conn, tid)
    return kb.request_changes(conn, tid, reason=reason,
                              expected_run_id=rclaim.current_run_id)


def _changes_runs(conn, tid: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM task_runs WHERE task_id = ? AND outcome = 'changes_requested'",
        (tid,),
    ).fetchone()[0]


def _events(conn, tid: str, kind: str | None = None) -> list:
    rows = conn.execute(
        "SELECT kind, payload FROM task_events WHERE task_id = ? ORDER BY id", (tid,),
    ).fetchall()
    out = [(r["kind"], r["payload"]) for r in rows]
    if kind is not None:
        out = [e for e in out if e[0] == kind]
    return out


def test_non_converging_card_stops_at_the_cap(kanban_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _cap(monkeypatch, 2)
    with kbc.connect() as conn:
        tid = kb.create_task(conn, title="never converges", assignee="dev")

        assert _review_round(conn, tid) == (True, "dev")  # round 1 granted
        assert kb.get_task(conn, tid).status == "ready"
        assert _review_round(conn, tid) == (True, "dev")  # round 2 granted
        assert kb.get_task(conn, tid).status == "ready"

        # Round 3 at cap 2: the verdict is recorded — history preserved — but no
        # rework is handed back; the card blocks for a human instead.
        ok, detail = _review_round(conn, tid)
        assert ok is True and detail is None
        task = kb.get_task(conn, tid)
        assert task.status == "blocked"
        assert task.block_kind == "needs_input"
        capped = [json_payload for kind, json_payload in _events(conn, tid, "rework_cap_reached")]
        assert len(capped) == 1
        assert _changes_runs(conn, tid) == 3
        blocked = _events(conn, tid, "blocked")
        assert blocked and "rework_round=2/2" in blocked[-1][1]


def test_reset_rework_grants_another_window_without_erasing_history(
    kanban_home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap(monkeypatch, 1)
    with kbc.connect() as conn:
        tid = kb.create_task(conn, title="cap then reset", assignee="dev")

        assert _review_round(conn, tid) == (True, "dev")
        ok, detail = _review_round(conn, tid)  # cap 1: second verdict blocks
        assert ok is True and detail is None
        assert kb.get_task(conn, tid).status == "blocked"
        assert _changes_runs(conn, tid) == 2
        events_before = _events(conn, tid)

        # An ordinary unblock must NOT grant more rounds: the next verdict re-blocks.
        assert kb.unblock_task(conn, tid) is True
        ok, detail = _review_round(conn, tid)
        assert ok is True and detail is None
        assert kb.get_task(conn, tid).status == "blocked"

        # The explicit reset grants a full extra window and records it as an event.
        assert kb.unblock_task(conn, tid, reset_rework=True) is True
        assert _events(conn, tid, "rework_reset")
        assert _review_round(conn, tid) == (True, "dev")
        assert kb.get_task(conn, tid).status == "ready"

        # Nothing was erased: every earlier run row and event survived.
        assert _changes_runs(conn, tid) == 4
        assert all(e in _events(conn, tid) for e in events_before)


def test_disabled_cap_never_blocks(kanban_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _cap(monkeypatch, 0)
    with kbc.connect() as conn:
        tid = kb.create_task(conn, title="unbounded by choice", assignee="dev")
        for _ in range(4):
            assert _review_round(conn, tid) == (True, "dev")
        assert kb.get_task(conn, tid).status == "ready"
        assert not _events(conn, tid, "rework_cap_reached")


def test_unset_config_falls_back_to_registered_default(
    kanban_home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cap is finite out of the box: unset user config falls back to the
    registered ``DEFAULT_CONFIG`` value (the reader and the registry entry stay
    in lockstep)."""
    from hermes_cli import config_effective
    from hermes_cli.config_defaults import DEFAULT_CONFIG

    monkeypatch.setattr(config_effective, "load_user_config_effective", lambda *a, **k: {})
    default = DEFAULT_CONFIG["kanban"]["max_review_rounds"]
    assert isinstance(default, int) and default >= 1  # finite: the cap ships enabled
    assert kb._rework_round_cap() == default

"""Destructive prune/archive/export previews must show the values they filtered on.

``hermes sessions prune --older-than 90 --min-cost 5`` selects on last activity and on the
est/actual cost sum, but the dry-run table showed only an unlabeled last-active timestamp
and no cost or token figures at all — the confirmation asked the user to approve a
cost-budget deletion without showing a single cost, and a ``--before`` start-date filter
was confirmed against the LAST-ACTIVITY column instead of the STARTED value it selected on
(upstream #133013). These drive the real SessionDB plus the real preview renderers.
"""

import re
import time
from types import SimpleNamespace

import pytest

from hermes_state import SessionDB
from hermes_cli import sessions_cmd
from hermes_cli.session_filters import format_epoch


@pytest.fixture()
def db(tmp_path):
    d = SessionDB(tmp_path / "state.db")
    yield d
    try:
        d.close()
    except Exception:
        pass


def _mk(db, sid, *, title=None, days=100, inp=2_000, outp=500, cost=1.5,
        started_days=None):
    db.create_session(sid, source="cli")
    if title is not None:  # titles are unique; only some fixtures want one to filter on
        db.set_session_title(sid, title)
    last = time.time() - days * 86400
    started = time.time() - (started_days if started_days is not None else days) * 86400
    with db._lock:
        db._conn.execute(
            "UPDATE sessions SET ended_at=?, started_at=?, last_activity_at=?, "
            "input_tokens=?, output_tokens=?, actual_cost_usd=?, message_count=2 WHERE id=?",
            (last, started, last, inp, outp, cost, sid),
        )
        db._conn.commit()


def _args(**overrides):
    base = dict(
        dry_run=True, yes=False,
        older_than=None, newer_than=None, before=None, after=None,
        source=None, title=None, like=None,
        min_tokens=None, max_tokens=None, min_cost=None, max_cost=None,
        min_messages=None, max_messages=None, min_tool_calls=None, max_tool_calls=None,
        archived=False, include_pinned=False, lineage_tips_only=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ─── selection surface: the projection carries the dims the filters select on ─────────


def test_prune_candidates_carry_token_and_cost_dims(db, tmp_path):
    _mk(db, "20260101_000000_aaaaaa", cost=6.0, inp=2_000, outp=500)
    _mk(db, "20260101_000001_bbbbbb", cost=0.25, inp=10, outp=5)  # below both budgets

    cands = db.list_prune_candidates(min_cost=1.0)
    by_id = {c["id"]: c for c in cands}
    assert set(by_id) == {"20260101_000000_aaaaaa"}  # the cost filter actually selected
    row = by_id["20260101_000000_aaaaaa"]
    assert row["tokens"] == 2_500  # in + out, the value the --min-tokens/--max-tokens filters use
    assert row["cost_usd"] == pytest.approx(6.0)  # actual, falling back to estimated


def test_prune_candidates_cost_dim_falls_back_to_estimate(db):
    _mk(db, "20260101_000000_aaaaaa", cost=0.0, title="budget run")
    with db._lock:
        db._conn.execute(
            "UPDATE sessions SET estimated_cost_usd=3.25, actual_cost_usd=NULL "
            "WHERE id='20260101_000000_aaaaaa'")
        db._conn.commit()

    (row,) = db.list_prune_candidates(title_like="budget")
    assert row["cost_usd"] == pytest.approx(3.25)


# ─── prune/archive confirmation rows ─────────────────────────────────────────────────


def test_dry_run_shows_the_cost_and_token_columns_it_filtered_on(db, tmp_path, capsys):
    _mk(db, "20260101_000000_aaaaaa", cost=6.0, inp=2_000, outp=500)

    rc = sessions_cmd._cmd_prune_or_archive(
        db, _args(min_cost=1.0, min_tokens=1_000, older_than="50"), "prune")
    out = capsys.readouterr().out
    assert rc in (0, None)
    assert "20260101_000000_aaaaaa" in out
    assert "$6.00" in out, "cost-budget prune must show the per-row cost it selected on"
    assert "2500 tok" in out
    assert "last-active" in out  # --older-than bounds activity, and the column says so


def test_dry_run_labels_the_started_column_when_a_start_bound_drove_selection(
        db, tmp_path, capsys):
    _mk(db, "20260101_000000_aaaaaa", days=10, started_days=200)

    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - 30 * 86400))
    rc = sessions_cmd._cmd_prune_or_archive(
        db, _args(before=cutoff, min_messages=1), "prune")
    out = capsys.readouterr().out
    assert rc in (0, None)
    assert "started " in out
    assert "last-active" not in out  # the STARTED bound selected; showing activity would misconfirm


def test_dry_run_without_dimension_filters_keeps_the_legacy_layout(db, tmp_path, capsys):
    _mk(db, "20260101_000000_aaaaaa", days=10, title="budget run")

    rc = sessions_cmd._cmd_prune_or_archive(
        db, _args(title="budget"), "prune")
    assert rc in (0, None)
    rows = [ln for ln in capsys.readouterr().out.splitlines() if "aaaaaa" in ln]
    assert len(rows) == 1
    legacy = re.fullmatch(
        r"  (?P<id>\S+)\s+(?P<ts>\S+ \S+|-)\s+(?P<source>\S+)\s+(?P<model>\S+|-)\s+"
        r"(?P<msgs>\d+) msgs  (?P<title>.*)",
        rows[0])
    assert legacy, f"unfiltered preview changed shape: {rows[0]!r}"
    # ...and it still shows last-active (not a relabeled column) with no added dimension fields.
    assert legacy.group("ts") == format_epoch(
        db.list_prune_candidates(title_like="budget")[0]["last_active"])
    for absent in ("started", "last-active", "tok", "$"):
        assert absent not in rows[0], f"dimension column leaked into the unfiltered preview: {rows[0]!r}"


# ─── export dry-run preview ──────────────────────────────────────────────────────────


def test_export_dry_run_preview_shows_the_dims_and_stays_minimal_without_them(
        db, capsys):
    _mk(db, "20260101_000000_aaaaaa", days=10, cost=4.5, inp=3_000, outp=250,
        title="budget run")

    sessions_cmd._print_dry_run_preview(
        db.list_prune_candidates(min_tokens=1_000),
        {"min_tokens": 1_000, "last_active_before": time.time()})
    out = capsys.readouterr().out
    row = next(ln for ln in out.splitlines() if "aaaaaa" in ln)
    assert "3250 tok" in row
    assert "last-active" in row

    # No dimension filters active → the historical two-column preview, byte-identical.
    capsys.readouterr()
    sessions_cmd._print_dry_run_preview(
        db.list_prune_candidates(title_like="budget"), {"title_like": "budget"})
    row = next(ln for ln in capsys.readouterr().out.splitlines() if "aaaaaa" in ln)
    assert row == "  20260101_000000_aaaaaa  cli"

"""Owner roster validation and audit (board policy: OWNERS.md v2).

The ``tasks.owner`` column is a routing-neutral accountability label, but it
is not free-for-all text: per the roster of record (OWNERS.md v2 §0), a value
is valid only if it names a real profile or the human operator. Fixture
profiles (coder, ops, ...) leaked into owner/assignee columns during the
Sep-13/14 dispatcher-test leak and are barred as owners.

Two primitives live here:

``validate_owner(value)``
    Strict roster check applied at every write that sets an explicit owner
    (``create_task(owner=...)`` and ``set_task_owner`` — both funnel through
    ``kanban_db._owner_or_none``). Blank/None is NOT an error: it falls
    through to the documented write-time default (``owner = created_by``).
    An unknown name raises ``ValueError`` listing the valid roster.

``audit_task_owners(conn)``
    Read-only, repeatable board audit (unlike the one-shot G4
    ``reconcile_task_owners`` backfill, this never writes). It reports, per
    OPEN card
    (``todo``/``triage``/``ready``/``running``/``blocked``/``review``):

    - ``unowned`` — no stored owner AND no creator to fall back on;
    - ``invalid`` — resolved owner (``owner ?? created_by``) outside the roster;
    - ``divergence`` — stored owner differs from ``assignee`` on an open card
      (OWNERS.md v2 §3: divergence on open cards is a defect flag, not a
      silent rewrite; terminal/archived cards are historical record and exempt).

    The roster itself is overridable via ``HERMES_OWNER_ROSTER`` (comma-
    separated) so tests and roster growth need no code change.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Optional

# Roster of record (OWNERS.md v2 §0): default = primary executor,
# voice = voice-scope executor, codeo1io = human operator.
DEFAULT_OWNER_ROSTER = ("default", "voice", "codeo1io")

# Statuses of cards still in play. Everything else (done/archived and the
# dispatcher-internal scheduled state) is historical record for audit purposes.
# 'triage' is a live pre-work status (kanban_create triage=True; the card is
# awaiting flesh-out) — an unowned or invalid-owner card sitting in triage is
# still a finding, so it must be audited, not skipped.
OPEN_STATUSES = ("todo", "triage", "ready", "running", "blocked", "review")


def owner_roster() -> tuple[str, ...]:
    """The active roster: ``HERMES_OWNER_ROSTER`` (comma-separated) or default."""
    raw = os.environ.get("HERMES_OWNER_ROSTER", "")
    names = tuple(n.strip() for n in raw.split(",") if n.strip())
    return names or DEFAULT_OWNER_ROSTER


def validate_owner(owner: Optional[str]) -> Optional[str]:
    """Strict roster check for an EXPLICIT owner value.

    None/blank passes through as None (the caller then applies the
    created_by write-time default — blank means "use the default", never
    "reject"). Any other value must be a roster name exactly (whitespace-
    stripped, case preserved — roster names are lowercase).

    Raises ``ValueError`` naming the roster on an unknown value.
    """
    if owner is None:
        return None
    value = str(owner).strip()
    if not value:
        return None
    roster = owner_roster()
    if value not in roster:
        raise ValueError(
            f"invalid owner {value!r}: must be one of {', '.join(roster)} "
            f"(roster of record: OWNERS.md v2; set HERMES_OWNER_ROSTER to override)"
        )
    return value


def audit_task_owners(conn: sqlite3.Connection) -> dict[str, Any]:
    """Read-only ownership audit over the whole board.

    Returns a report dict with per-bug-class ``counts`` and id lists, plus a
    combined ``issues`` list of ``{id, kind, detail}`` sorted by (kind, id).
    Exit-condition for a healthy board: ``counts["unowned"] == 0``,
    ``counts["invalid"] == 0`` (divergence is advisory — legitimate
    owner/assignee splits exist once accountability and routing part ways).
    """
    roster = set(owner_roster())
    rows = conn.execute(
        "SELECT id, status, owner, assignee, created_by FROM tasks ORDER BY id"
    ).fetchall()

    unowned: list[str] = []
    invalid: list[dict[str, str]] = []
    divergence: list[dict[str, str]] = []
    open_cards = 0

    for r in rows:
        status = r["status"]
        if status not in OPEN_STATUSES:
            continue
        open_cards += 1
        owner = (r["owner"] or "").strip() or None
        resolved = owner or (r["created_by"] or "").strip() or None
        if resolved is None:
            unowned.append(r["id"])
        elif resolved not in roster:
            invalid.append({"id": r["id"], "owner": resolved})
        if owner is not None and owner != r["assignee"]:
            divergence.append(
                {"id": r["id"], "owner": owner, "assignee": r["assignee"] or "(none)"}
            )

    issues = (
        [{"id": i, "kind": "unowned", "detail": "no owner and no created_by fallback"} for i in unowned]
        + [{"id": d["id"], "kind": "invalid", "detail": f"owner {d['owner']!r} not in roster"} for d in invalid]
        + [{"id": d["id"], "kind": "divergence",
            "detail": f"owner {d['owner']!r} != assignee {d['assignee']!r}"} for d in divergence]
    )
    issues.sort(key=lambda i: (i["kind"], i["id"]))
    return {
        "roster": sorted(roster),
        "open_cards": open_cards,
        "counts": {
            "unowned": len(unowned),
            "invalid": len(invalid),
            "divergence": len(divergence),
        },
        "unowned": unowned,
        "invalid": invalid,
        "divergence": divergence,
        "issues": issues,
    }

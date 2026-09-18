# Kanban: routing-neutral per-task owner field — brainstorm

Status: brainstorm (run `30c1df938db647e4a8e08bfe9b05fd09`). No code changed in this phase.

## Requirement

Add a per-task **owner** field to the kanban board that is:

1. **Routing-neutral** — never consulted by the dispatcher; changing it must not
   affect claim/spawn/promotion behavior or failure counters.
2. **Defaults to creator** — a new task's owner is whoever created it.
3. **Transferable** — an operator can move ownership to another name later.
4. **Displayed in show/list** — visible on `hermes kanban show`, `hermes kanban
   list` (human + `--json`), and the read paths that mirror them.

The point is to separate *accountability* (who owns the outcome — typically the
human/orchestrator that filed the card) from *routing* (the `assignee` profile
the dispatcher spawns). Today those are conflated: prose in
`hermes_cli/kanban_decompose.py:139` already says "a task is never stranded for
lack of an owner" — meaning the *assignee*. A routing-neutral owner gives the
board a human-facing "whose card is this" answer that survives reassignment and
worker churn.

## What exists today (grounding)

- **Schema**: `tasks` has `assignee` (dispatch routing) and `created_by`
  (free-text creator stamp: profile name, `"dashboard"`,
  `HERMES_PROFILE or "worker"` from the tool surface, or even a creating task
  id for graph-derived children — `hermes_cli/kanban_db.py:2463-2493`). There
  is no `owner` column.
- **Routing is keyed on `assignee` only**: the dispatcher
  (`kanban_db_dispatch.py`) reads `assignee` everywhere it decides what to
  spawn; `list_tasks` filters/sorts by it; `--mine` maps to
  `_profile_author()`; `known_assignees()` feeds pickers.
- **`assign_task`** (`kanban_db.py:1500`) is the transfer precedent — and the
  anti-pattern for this feature: it refuses while a task is
  claimed+running and **resets `consecutive_failures`** because a new
  assignee is a new dispatch bet. An owner change must do neither.
- **Additive-column migration** is a solved problem: `_LATER_TASK_COLUMNS` in
  `hermes_cli/kanban_db_connect.py:794` ALTER-TABLEs later columns
  (`completion_contract` is the most recent TEXT example), with a
  first-add-only backfill precedent (`delivery_mode`).
- **Per-task override write pattern**: `_set_task_override`
  (`kanban_db.py:1531`) — `write_txn` → refuse archived → UPDATE →
  `_append_event` → `notify_task_updated` observer after commit.
- **Display surfaces**: `hermes kanban show` field list (`kanban.py:~507-527`),
  list line formatter `_fmt_task_line` (`kanban_output.py`), CLI `--json`
  `_TASK_DICT_FIELDS`, model-tool summaries `_TASK_FIELDS` /
  `_TASK_SUMMARY_FIELDS` (`tools/kanban_tools.py:310-315`), dashboard REST
  (`plugins/kanban/dashboard/plugin_api.py` — `CreateTaskBody`/`UpdateTaskBody`
  + PATCH at ~646), desktop drawer (`apps/desktop/src/plugins/kanban/drawer.tsx`
  already renders `created_by` at line 784).
- **Export/import** (`kanban_transfer.py`): `_scrub_local_state` strips only
  machine-local state (claims, PIDs, paths, notify subs). A person-facing
  `owner` is board data, not machine state — it should survive export.
- **Docs**: `website/docs/user-guide/features/kanban.md` (core concepts, CLI
  reference), `cron/AGENTS.md` (verb list).

## Design space

### A. New `owner` column (additive migration) — RECOMMENDED

Add `owner TEXT` to `tasks` via the standard `_LATER_TASK_COLUMNS` + `SCHEMA_SQL`
path; default at write time; transfer via a new verb.

- **Defaults**: `create_task(..., owner=None)` resolves `owner = owner or
  created_by`, so every creator surface (CLI, tools, dashboard, swarm,
  decompose, specify) gets the default with zero per-caller changes.
- **Legacy rows**: one-shot backfill `UPDATE tasks SET owner = created_by WHERE
  owner IS NULL` on first column-add (the `delivery_mode` first-add backfill is
  the precedent). Post-migration, `owner IS NULL` means "explicitly cleared".
- **Transfer**: new verb `hermes kanban owner <task-id> <name>` (+ `none`/`-` to
  clear, mirroring assign's unassign vocabulary) backed by
  `set_task_owner()` on the `_set_task_override` pattern: refuse `archived`,
  **allowed while running** (routing-neutral is the whole point), event kind
  `owner_transferred` with `{from, to}` payload, then
  `notify_task_updated(conn, tid, ("owner",))`.
- **Display**: `show` gains `owner:` after `assignee`; list human line gains a
  compact owner column (owner and assignee will usually *differ* — owner is the
  creator/human, assignee the worker — so "hide when equal" would hide it
  almost never; always showing is simpler and honest); `owner` added to
  `_TASK_DICT_FIELDS`, `_TASK_FIELDS`, `_TASK_SUMMARY_FIELDS`.
- **Create flag**: `--owner` on `hermes kanban create` and an `owner` param on
  the `kanban_create` model tool (orchestrator fan-out can file a card already
  owned by the requester).

Tradeoffs:

- ➕ One plain, queryable, sortable column; every read site (Python, JSON, TS)
  reads `t.owner` with no fallback logic; survives export; migration machinery
  already exists; smallest diff at each surface.
- ➕ Routing-neutrality is enforceable and testable: `set_task_owner` provably
  touches only `owner` (no `consecutive_failures`, no claim, no assignee), and
  the dispatcher provably never reads the column.
- ➖ Touches many files (schema, db op, CLI parser+handler, output helpers,
  tools, dashboard API, desktop drawer, docs) — inherent to any task field, not
  to this choice.
- ➖ New event kind `owner_transferred` is inert for gateway notify delivery
  (subs push `completed`/`blocked`/`gave_up` only) — it lands in `show` events
  and the dashboard activity feed. Acceptable; adding delivery is a separate
  opt-in later if anyone asks.

### B. Overload `assignee` (no new field)

Treat "owner" as a flavor of assignee or a second assignee slot.

- ➕ No schema change.
- ➖ **Violates the requirement outright**: `assignee` *is* routing — it decides
  which profile the dispatcher spawns, resets failure counters on change,
  gates `--mine`, feeds pickers. A routing-neutral field cannot live there.
- ➖ Owner (a human/accountability name) and assignee (a worker profile) are
  legitimately different values at the same time; one column cannot hold both.

Rejected.

### C. Encode owner in task body / comments / run metadata

Stamp `owner: alice` into the body or emit a comment on transfer.

- ➕ Zero schema/surface changes.
- ➖ Not structured data: no filtering, no JSON field, no dashboard editing,
  fragile text parsing, invisible to SQL, and every display surface would need
  a parser. Transfer history via comments is already available *in addition*
  (the event log covers it), not instead.

Rejected as the mechanism (the `owner_transferred` event keeps the audit trail
anyway).

### D. Side table `task_owners` (task_id, owner, since)

- ➕ Keeps transfer history as rows.
- ➖ Overkill for a single scalar: breaks the single-row `Task.from_row` read
  model that every surface shares; every reader becomes a join; history is
  already served by `task_events`. Violates "extend, don't duplicate".

Rejected.

### E. Generic key-value `task_attributes` JSON column

A generic extension point (owner being the first key).

- ➕ One migration buys infinite future fields.
- ➖ **Speculative infrastructure** by the repo's own rubric — no second
  consumer exists; keys are unqueryable/unvalidatable; display surfaces need
  per-key code anyway, so it saves almost nothing. If a second metadata field
  is ever wanted, it can be added additively then.

Rejected.

## Recommended direction

**Approach A**, with these sub-decisions:

1. **Eager backfill over lazy fallback.** Backfill `owner = created_by` on
   first column-add rather than making every read path do
   `COALESCE(owner, created_by)` (Python dataclass, CLI JSON, tool dicts, TS
   types, SQL filters would each need the fallback — five places to forget).
   Write-time default keeps the invariant for new rows.
2. **Dedicated `owner` verb, not `edit`.** `hermes kanban edit` is
   recovery-field editing on completed tasks (`--result`); overloading it would
   blur two lifecycles. `owner` mirrors `assign` in shape (single task id).
   Bulk ids (`_bulk_ids`) are a trivial follow-up if ever wanted.
3. **No state guard beyond archived.** Transfer is allowed while running —
   explicitly unlike `assign_task`. This *is* the routing-neutrality contract
   and should be asserted in tests (transfer succeeds under a live claim;
   `consecutive_failures`, `claim_lock`, `assignee` unchanged; next dispatch
   tick unaffected).
4. **Model tools: read + create-param only.** `owner` appears in
   `kanban_show`/`kanban_list` output and as a `kanban_create` param. No
   dedicated `kanban_transfer_owner` tool yet — no consumer (footprint ladder:
   extend existing first); CLI + dashboard PATCH cover the human flows. Add the
   `owner` verb to `_DELEGATED_CHILD_DENIED_ACTIONS` so delegated children
   can't grab cards.
5. **Dashboard REST ready, SPA display out of tree.** Add `owner` to task
   serialization, `CreateTaskBody`, `UpdateTaskBody`, and the PATCH branch in
   `plugin_api.py`. The web SPA is shipped prebuilt (`dist/index.js`, no
   in-tree source) so its UI update is not part of an in-tree change; the
   desktop drawer (`apps/desktop/src/plugins/kanban/drawer.tsx`) *is* in-tree
   and gets an owner MetaRow (inline editor optional, mirroring the assignee
   one).
6. **Include a `--owner` list filter** (symmetry with `--assignee`; ~5 lines in
   `list_tasks` which is already table-driven). No index (assignee has none
   either; boards are small). No `known_owners` endpoint — owners are free
   text, not dispatch targets.
7. **Naming**: column `owner`, event kind `owner_transferred`, CLI verb
   `owner`. Docs must state the owner/assignee distinction in one line each
   place `assignee` is defined (`kanban.md` core concepts + CLI reference,
   `cron/AGENTS.md` verb list).

### Touchpoint inventory (for the plan phase)

| File | Change |
|---|---|
| `hermes_cli/kanban_db.py` | `SCHEMA_SQL` column; `Task` field + column lists; `create_task` kwarg + INSERT + default; `set_task_owner()`; `list_tasks(owner=…)` |
| `hermes_cli/kanban_db_connect.py` | `_LATER_TASK_COLUMNS` entry + first-add backfill |
| `hermes_cli/kanban_parser.py` | `owner` verb; `--owner` on `create`/`list` |
| `hermes_cli/kanban.py` | `_cmd_owner` + handler-table entry; `_DELEGATED_CHILD_DENIED_ACTIONS`; show field |
| `hermes_cli/kanban_output.py` | `_fmt_task_line` owner column; `_TASK_DICT_FIELDS` |
| `tools/kanban_tools.py` | `owner` in `_TASK_FIELDS`/`_TASK_SUMMARY_FIELDS`; `kanban_create` param |
| `plugins/kanban/dashboard/plugin_api.py` | serialization, `CreateTaskBody.owner`, `UpdateTaskBody.owner`, PATCH branch |
| `apps/desktop/src/plugins/kanban/` | `types.ts` field; `drawer.tsx` MetaRow |
| `website/docs/user-guide/features/kanban.md`, `cron/AGENTS.md` | concepts, CLI reference, verb list |

Callers needing **no** change (write-time default covers them): `kanban_swarm`,
`kanban_decompose`, `kanban_specify`, dashboard create, `kanban_create` tool —
they already pass `created_by`. Export/import needs no change (owner is not
machine-local). Test targets: `tests/hermes_cli/test_kanban*.py`,
`tests/tools/test_kanban*.py` (behavior contracts: default-to-creator, transfer
under live claim without counter reset, migration backfill, display in
show/list JSON).

## Incidental finding

`website/docs/user-guide/features/kanban.md:804` documents `hermes kanban edit`
as a title/body/priority editor, but the parser and `_cmd_edit` only support
`--result` recovery editing on done tasks (`kanban_parser.py:288`,
`kanban.py:889`). Stale doc — worth a one-line fix whenever docs are next
touched; unrelated to this feature.

## Open questions — resolved autonomously

- Owner vs assignee semantics → distinct field (requirement: routing-neutral).
- Legacy default → eager backfill at migration, not lazy COALESCE (one write
  vs five fallback sites).
- Verb → new `owner` verb + `--owner` on create/list; `edit` stays
  recovery-only.
- Guardrails → refuse archived only; allowed while running (that is the
  neutrality contract, tested).
- Worker exposure → read display + create param; no transfer tool (defer until
  a consumer exists); CLI verb denied for delegated children.
- Dashboard SPA → API yes, prebuilt dist out of in-tree scope; desktop drawer
  in-tree.
- Clearing owner → allowed via `none`/`-` for symmetry with assign's unassign.

## Enforcement layer — roster validation + board audit (follow-up card t_c39dfaac)

The owner field shipped routing-neutral and *free text*. The enforcement layer
(OWNERS.md v2, roster of record §0) tightens exactly one thing on top: an
**explicit** owner value on a write must name a real identity — one of
`default`, `voice`, `codeo1io` — or the write is rejected with a `ValueError`
naming the roster. Everything else is unchanged and deliberately so:

- **Blank/None is never rejected** — it means "use the default" and falls
  through to the write-time `owner = created_by` stamp (which may itself be a
  provenance string like `"user"` from the CLI or `"auto-decomposer"`;
  provenance is never validated — it is a record, not a choice).
- **`created_by` fallback values are not validated** — the default path stamps
  whatever the creating surface recorded. An off-roster *default* is not a
  write-time error; it becomes visible via the audit below instead (that is
  the point of an audit: it sees what validation cannot, because defaults and
  pre-validation rows cannot raise at write time).
- **Read paths never validate** — `list_tasks(owner=...)` filtering by an
  unknown name is a legitimate empty result, not an error.
- **Roster override**: set `HERMES_OWNER_ROSTER=alpha,beta` (comma-separated)
  to grow/change the roster without code change; unset it and the roster of
  record (`default, voice, codeo1io`) applies.
- **Raw-SQL system writes are exempt**: `reconcile_task_owners` (backfill) and
  decompose fan-out stamp provenance/creator values by design and must not
  raise on legacy names.

New primitives (`hermes_cli/kanban_owner.py`):

- `validate_owner(value)` — strict roster check for explicit values; raises
  `ValueError("invalid owner 'x': must be one of …")` on unknown names.
- `audit_task_owners(conn)` — **read-only, repeatable** board audit over OPEN
  cards (`todo/triage/ready/running/blocked/review`; triage is a live
  pre-work status — cards there still need a resolvable owner); reports
  `unowned` (no owner and
  no `created_by` fallback), `invalid` (resolved owner outside the roster), and
  `owner != assignee` **divergence** (OWNERS.md v2 §3 invariant — advisory:
  legitimate owner/assignee splits exist once accountability and routing part
  ways). Exit condition for a healthy board: `unowned == 0 and invalid == 0`.
  Terminal/archived cards are historical record and exempt.

CLI: `hermes kanban owner-audit` (text or `--json`) prints counts + per-issue
detail and exits 1 while unowned/invalid open cards exist. Unlike the one-shot
`owner-reconcile` backfill, it never writes.

Live board at enforcement-merge time (2026-09-18, 210 open cards): the audit
surfaces the two known defect classes — the ~1,5xx fixture corpus (§5.3:
deliberately unowned until area-3 disposition) and a handful of pre-validation
rows with `owner='user'` (CLI provenance default) or owner/assignee split.
These are findings, not blockers: the audit exists to keep them visible until
dispositioned.


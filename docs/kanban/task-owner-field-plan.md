# Implementation plan — kanban routing-neutral per-task owner field

Companion to `docs/kanban/task-owner-field.md` (brainstorm; recommended Approach A).
Scope: add `owner` to kanban tasks — defaults to creator, transferable, displayed in
show/list, never consulted by dispatch.

## Design contract (invariants every task below preserves)

1. **Routing-neutral**: the dispatcher (`kanban_db_dispatch.py`), promotion/reclaim
   logic, `known_assignees`, `--mine`, and every spawn decision are owner-blind.
   `set_task_owner` touches ONLY `tasks.owner` — never `assignee`, `claim_lock`,
   `consecutive_failures`, `last_failure_error`, or status.
2. **Default at write time**: `create_task` resolves `owner = owner or created_by`.
   No lazy `COALESCE` in read paths.
3. **One-shot legacy backfill**: on first column-add, `UPDATE tasks SET owner =
   created_by WHERE owner IS NULL` (runs once; re-runs are no-ops). Post-migration
   `NULL` = explicitly cleared owner.
4. **Owner is free text** (person/team name), NOT validated against profiles —
   it is an accountability label, not a dispatch target. Strip whitespace; `""` is
   stored/read as NULL.
5. **Transfer allowed while running** under a live claim (the deliberate contrast
   with `assign_task`, which raises 409-style); refused only on `archived` and
   unknown ids (returns False).
6. **Audit**: transfer records a `task_events` row, kind `owner_transferred`,
   payload `{"from": <old>, "to": <new>}`, then fires
   `notify_task_updated(conn, tid, ("owner",))` after commit. Gateway notify
   delivery ignores the new kind (by design — subs deliver
   completed/blocked/gave_up only).
7. **Export/import**: owner travels with the board (`_scrub_local_state` in
   `hermes_cli/kanban_transfer.py` untouched — owner is board data, not
   machine-local state).

---

## Task breakdown

Ordered by dependency; T1–T2 are the core, T3–T6 are surfaces, T7–T8 polish/docs,
T9–T10 tests/verification.

### T1 — Schema, dataclass, create default, migration backfill

**`hermes_cli/kanban_db.py`**
- `SCHEMA_SQL` tasks table: add `owner TEXT` column with the standard comment
  block (place after `created_by` region, before `claim_lock`):
  `-- Routing-neutral accountability label (who owns the outcome). Defaults to creator; never consulted by dispatch.`
- `Task` dataclass: field `owner: Optional[str] = None` (near `session_id`,
  after `completion_contract`).
- Column tuples: add `"owner"` to `_TASK_OPTIONAL_COLUMNS` AND to
  `_TASK_EMPTY_IS_NULL_COLUMNS` (so `""` reads as None, matching
  `model_override` treatment).
- `create_task(...)`: new kwarg `owner: Optional[str] = None`; canonicalize
  (`_strip`; empty→None); after `assignee = _canonical_assignee(assignee)` add
  `owner = _owner_or_none(owner) or created_by`; add `owner` to the INSERT
  column list + values tuple (kanban_db.py ~1329-1345).
- New helper `def set_task_owner(conn, task_id, owner) -> bool` placed next to
  `assign_task` (~line 1500): resolve old owner via SELECT, `write_txn`:
  refuse archived (RuntimeError, message mirroring `_set_task_override`'s
  `archived_msg` style), UPDATE `tasks.owner`, `_append_event(conn, tid,
  "owner_transferred", {"from": old, "to": new})`; after commit
  `notify_task_updated(conn, tid, ("owner",))`; return False on unknown id.
  (Deliberately NOT via `_set_task_override`: that helper's payload/event-kind
  shape differs and it takes prebuilt SQL; a dedicated small function keeps the
  from/to audit payload explicit. Either is acceptable — implementer may reuse
  `_set_task_override` if they generalize it, but the event payload MUST carry
  from/to.)
- `list_tasks(...)`: add `owner: Optional[str] = None` kwarg; add
  `("owner", _strip_owner(owner))` to the filter loop tuple list (~1477).

**`hermes_cli/kanban_db_connect.py`**
- `_LATER_TASK_COLUMNS`: append `("owner", "owner TEXT")`.
- `_migrate_add_optional_columns`: in the `_LATER_TASK_COLUMNS` loop, on
  first-add of `owner` (mirror the `model_override` special-case shape at
  ~865-870 and the `delivery_mode` first-add backfill precedent): run
  `conn.execute("UPDATE tasks SET owner = created_by WHERE owner IS NULL")`.
  Guard: only when the column was just added (the loop already knows).

Acceptance: fresh DB + legacy DB (pre-owner schema built by raw SQL, pattern of
`tests/hermes_cli/test_kanban_db.py:92`) both open, migrate idempotently, and
every task row has owner = created_by after migration; `create_task` with
`owner=None` stamps `created_by`.

### T2 — CLI: verb, flags, show, list, denial gate

**`hermes_cli/kanban_parser.py`**
- New verb after `assign` (~line 236):
  `_cmd("owner", [_TASK_ID, _arg("owner", help="Owner name (or 'none' to clear)")], help="Set, transfer, or clear a task's owner (routing-neutral metadata)")`.
- `create` (~line 148): `_arg("--owner", help="Task owner (defaults to the creator name)")`.
- `list` (~line 218): `_arg("--owner", help="Filter by owner")`.

**`hermes_cli/kanban.py`**
- `_cmd_owner(args)` mirroring `_cmd_assign` (~572):
  `owner = _none_owner(args.owner)` (new tiny helper or reuse `_none_profile`
  — same `none`/`-`/`null` vocabulary; reuse `_none_profile` directly to avoid
  a duplicate, or rename-free local alias; keep it one-liner) →
  `kb.set_task_owner(conn, args.task_id, owner)` →
  `_ok_or_err(ok, f"no such task: {args.task_id}", f"Owner of {args.task_id} set to {owner or '(none)'}")`
  (wrap RuntimeError → stderr + rc 1, same as `_cmd_set_model`).
- `_HANDLERS` (~1241): `"owner": _cmd_owner`.
- `_DELEGATED_CHILD_DENIED_ACTIONS` (~215): add `"owner"`.
- `_cmd_create` (~365): pass `owner=getattr(args, "owner", None)` into
  `create_task`.
- `_cmd_list` (~419): pass `owner=getattr(args, "owner", None)` into
  `list_tasks`.
- `_cmd_show` field list (~507): `field("owner", task.owner or "-")` directly
  after `assignee`.

**`hermes_cli/kanban_output.py`**
- `_TASK_DICT_FIELDS`: add `"owner"` (right after `"assignee"`).
- `_fmt_task_line`: insert an owner column after assignee:
  `owner = t.owner or "-"` →
  `f"{icon} {t.id}  {t.status:8s}  {assignee:20s}{owner:16s}{tenant}  {t.title}"`.
  (Always shown: owner usually ≠ assignee — creator/human vs worker profile —
  so hide-when-equal would almost never hide.)

Acceptance: `hermes kanban create --owner alice` stamps owner; `show` prints
`owner:`; `list` line shows owner; `list --owner alice` filters; `list --json`
includes `"owner"`; `owner <id> bob` then `owner <id> none` round-trips; a
delegated child (`HERMES_KANBAN_TASK` set) running verb `owner` is refused.

### T3 — Model tools (read display + create param)

**`tools/kanban_tools_schemas.py`**
- `KANBAN_CREATE_SCHEMA` (~351): add property `"owner": _prop("string",
  "Optional owner label recorded on the card (accountability, not routing — defaults to the creating profile).")`.

**`tools/kanban_tools.py`**
- `_TASK_FIELDS` (~310) and `_TASK_SUMMARY_FIELDS` (~314): add `"owner"` after
  `"assignee"`.
- `_handle_create` (~850-862): pass `owner=str(args["owner"]).strip() or None
  if args.get("owner") is not None else None` into `create_task`.

Acceptance: `kanban_show`/`kanban_list` tool results include `owner`;
`kanban_create(..., owner="alice")` lands (CLI/db layer guarantees the
created_by default otherwise). No new tool, no toolset change (`toolsets.py`
untouched) — footprint ladder rung 1 (extend existing).

### T4 — Dashboard REST API

**`plugins/kanban/dashboard/plugin_api.py`**
- `CreateTaskBody` (~373): `owner: Optional[str] = None` (kwarg name matches
  `create_task`, so `**payload.model_dump()` just works).
- `UpdateTaskBody` (~490): `owner: Optional[str] = None` +
  `clear_owner: bool = False` (PATCH `None` = not sent; the established
  clear-signal convention at ~509-517).
- `_OVERRIDE_OPS` (~594) or a sibling branch in `update_task` (~646): apply via
  `kanban_db.set_task_owner(conn, task_id, payload.owner or None)` when
  `payload.clear_owner or payload.owner is not None`; refused-message
  `"owner refused"`; map ValueError/RuntimeError → 400. Prefer a small
  dedicated branch next to the assignee branch (owner is not an "override" —
  no next-dispatch semantics).
- Serialization: `_task_dict` uses `asdict(task)` — owner flows automatically
  once the dataclass has it. No change needed there.
- `BulkTaskBody` + `_bulk_apply_one`: add `owner`/`clear_owner` for symmetry
  (optional; include only if trivial — it is the same two lines; if skipped,
  record in PR notes).

Acceptance: `POST /tasks` with `owner`; `PATCH /tasks/{id}` with
`{"owner": "bob"}` and `{"clear_owner": true}`; GET returns owner in task
dict. Web SPA (`dist/`) is prebuilt/out-of-tree — no UI change in this PR.

### T5 — Desktop app (display)

**`apps/desktop/src/plugins/kanban/`**
- `types.ts` (~99): `owner?: null | string` next to `created_by`.
- `i18n.ts` (~123): `metaOwner: 'Owner'` (all locales follow the existing
  pattern — add to the English block; other-locale keys follow the file's
  convention).
- `drawer.tsx` (~784): `<MetaRow label={k.metaOwner}>{task.owner ?? '—'}</MetaRow>`
  beside `metaCreatedBy`. Display-only (transfer via CLI/REST; inline editor
  deferred — see provisional).

Acceptance: `pnpm --filter desktop typecheck`/existing vitest suite still
passes; drawer shows owner row.

### T6 — Docs

- `website/docs/user-guide/features/kanban.md`:
  - Core concepts "Task" bullet (~115): add `optional owner (accountability
    label; defaults to creator; routing-neutral — distinct from assignee)`.
  - Tool table `kanban_create` row (~361): mention `owner`.
  - CLI reference (~781+): add `hermes kanban owner <id> <name|none>` line;
    document `create --owner`, `list --owner`.
  - Opportunistic one-line fix: stale `kanban edit` description at ~804
    (parser only supports `--result` recovery editing).
- `cron/AGENTS.md` verb list: add `owner` after `assign`.
- `website/docs/reference/tools-reference.md`: check the `kanban` toolset table
  (~131) — add `owner` mention to `kanban_create`/`kanban_list` rows only if
  those rows enumerate params (they currently don't; likely no change).

### T7 — Python tests (new + extensions)

**New `tests/hermes_cli/test_kanban_owner.py`** (real sqlite via existing
kanban_home fixtures; behavior contracts, no change-detectors):
1. `create_task(owner=None)` → owner == created_by; explicit owner honored;
   `--owner` CLI flag and tool param reach the DB.
2. `set_task_owner`: unknown id → False; transfer updates column, appends
   `owner_transferred` event with `{"from","to"}`; `none`/`-`/`""` → NULL.
3. **Routing-neutrality**: task with `status="running"` + fake live
   `claim_lock` → transfer succeeds AND `assignee`, `claim_lock`,
   `consecutive_failures`, `last_failure_error`, `status` are byte-identical
   before/after.
4. Archived task → RuntimeError, owner unchanged.
5. Migration: build a pre-owner legacy DB (raw-SQL pattern from
   `tests/hermes_cli/test_kanban_db.py:92`), insert rows with `created_by`,
   run connect/migration → owner backfilled == created_by; second open is a
   no-op (idempotent); a NULL owner set AFTER migration survives reopening
   (not re-backfilled — first-add guard works).
6. CLI: `show` output contains `owner:`; `list` line contains owner value;
   `list --json` has `"owner"` key; `list --owner x` filters correctly.
7. Denied-action gate: `HERMES_KANBAN_TASK` set + `owner` verb → refused.

**Extend `tests/tools/test_kanban_tools.py`**: `kanban_create` owner param
lands; `kanban_show`/`kanban_list` include owner.

**Extend dashboard tests** (find the existing plugin_api test file under
`tests/` — grep `plugin_api` / `TestClient` in `tests/hermes_cli/`): PATCH
owner / clear_owner / POST owner.

### T8 — Desktop tests (optional but cheap)

Extend `apps/desktop/src/plugins/kanban/drawer.test.tsx`: renders owner
MetaRow when set. (Vitest suite — Python-side tests would not run on a JS-only
lane; ours is mixed, keep the TSX assertion in vitest per placement policy.)

### T9 — Verification (pre-validation gate; NOT final_validation/commit)

```bash
scripts/run_tests.sh tests/hermes_cli/test_kanban_owner.py
scripts/run_tests.sh tests/hermes_cli/test_kanban_cli.py tests/hermes_cli/test_kanban_db.py \
  tests/hermes_cli/test_kanban_db_init.py tests/tools/test_kanban_tools.py
# plus the dashboard-API test file chosen in T7
scripts/run_tests.sh tests/hermes_cli/            # kanban family sweep
```

Manual E2E against a temp `HERMES_HOME`: `hermes kanban init && create
--owner alice`, `show`, `owner <id> bob`, `list --owner bob`, `list --json |
jq '.[].owner'`, legacy-DB open. Desktop: typecheck + drawer render.

---

## Explicitly out of scope (deferred / provisional)

- Dedicated `kanban_transfer_owner` model tool (no consumer; CLI + REST cover it).
- Gateway notify delivery for `owner_transferred` events.
- Inline owner editor in the desktop drawer; web SPA (dist) display.
- `owner` sort order in `VALID_SORT_ORDERS`; `known_owners` endpoint; owner
  index (assignee has none either); owner stats.
- Any dispatcher/`--mine`/`known_assignees` change — owner must stay unread
  there.

## Risk notes

- **Column-tuple misses** are the classic failure: owner must appear in
  SCHEMA_SQL, `_LATER_TASK_COLUMNS`, `Task`, `_TASK_OPTIONAL_COLUMNS`,
  `_TASK_EMPTY_IS_NULL_COLUMNS`, the INSERT, and both tools/CLI field tuples —
  the test matrix in T7 cross-cuts them so a miss goes red.
- **Backfill correctness**: fire only on first-add (guard on the loop's
  just-added flag), else a cleared owner would resurrect on every open.
- **Do not reuse `assign_task`** for owner writes — it carries claim-guard +
  failure-counter semantics that are exactly wrong here.
- Docs drift: update the three doc surfaces in the same change (root policy).

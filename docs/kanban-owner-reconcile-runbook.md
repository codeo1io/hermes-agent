# Runbook: post-deploy owner reconciliation (G4) + effective_owner (G3)

Branch: `fix/owner-g3-g4` (off lane merge head `e2c1ce2121`, run
`30c1df938db6`). Spec of record: `docs/kanban-owner.md` §5 (branch
`docs/kanban-owner-spec`). Implements the two verified-remaining gaps of the
owner feature: G3 (read-path display fallback) and G4 (post-deploy one-shot
guarded reconciliation).

## Background (why this exists)

The one-shot first-add backfill in `_migrate_add_optional_columns` fires only
when the `owner` COLUMN is first added to a board. The live board's column was
added out-of-band on 2026-09-14; the running install still INSERTs without
owner. Every task created in that mixed-version window (and until the
owner-writing code is deployed) is `owner IS NULL` with `created_by` set — the
first-add backfill will never re-run for them. Measured 2026-09-15:
799 tasks total, 781 owner-NULL, 24 NULL-but-creator-set (growing).

G3 closes the read side (display): `Task.effective_owner` =
`owner ?? created_by ?? None`, used by CLI `show`/`list` and the dashboard
`_task_dict`. Stored value stays NULL (honest, "explicitly cleared" sentinel
preserved); SQL stays COALESCE-free.

G4 closes the write side: `reconcile_task_owners(conn, dry_run=)` re-points
window rows at their creator, guarded by `PRAGMA user_version` (verified
unused across the codebase; 0 = not yet reconciled, 1 = done) so it runs
exactly once per board. Explicit-only trigger via the CLI verb — no auto-run
at connect, deliberately: the dry run must be able to preview the live board
before anything writes.

## How to rerun the backfill (post-deploy, on the live board)

```bash
# 1. Dry run first (DEFAULT — never apply blind):
hermes kanban owner-reconcile
# → "owner reconciliation [DRY RUN]: would repoint N task(s) ..." + per-task
#   (id, from, to) lines. Inspect the list. --json for the machine-readable report.

# 2. Apply:
hermes kanban owner-reconcile --apply
# → same report, "applied: N task(s) changed; gate set (user_version = 1)."

# 3. Verify:
hermes kanban owner-reconcile          # → "already ran ... nothing to do"
sqlite3 -readonly ~/.hermes/kanban.db "PRAGMA user_version;"   # → 1
sqlite3 -readonly ~/.hermes/kanban.db \
  "SELECT COUNT(*) FROM tasks WHERE owner IS NULL AND created_by IS NOT NULL AND created_by != '';"
# → 0
```

Each changed row gets an audit event: `owner_reconciled {from, to,
backfill: true}` — visible in `hermes kanban show <id>` events and the
dashboard drawer.

## Auditable / reversible

- Report: every run prints (id, from, to) per change; `--json` returns
  `{ran, dry_run, already_reconciled, candidates, changed, changes[]}`.
- Audit trail: `owner_reconciled` events persist in `task_events` per task.
- Reversible: undo = `hermes kanban owner <id> none` per task, or
  `UPDATE tasks SET owner = NULL WHERE ...` using the `changes[]` list / the
  `owner_reconciled` events as the map of what was touched.
- Idempotent: gate makes second runs no-ops; even without the gate the UPDATE
  is a fixed point (only touches `owner IS NULL` rows).

## Known limitation (accepted, spec §5)

Explicit clears made BEFORE reconciliation are indistinguishable from window
rows and will be overwritten — this is why reconciliation is explicit and
prompt post-deploy, not deferred.

## Tests

`tests/hermes_cli/test_kanban_owner_reconcile.py`:

- `test_reconcile_repoints_window_rows_and_sets_gate`
- `test_reconcile_dry_run_writes_nothing_but_reports_plan`
- `test_reconcile_is_one_shot_gate_blocks_second_run`
- `test_reconcile_idempotent_without_gate`
- `test_reconcile_skips_null_creator_rows`
- `test_reconcile_clear_after_reconcile_survives_reopen`
- `test_effective_owner_falls_back_to_created_by`
- `test_effective_owner_prefers_explicit_owner`
- `test_effective_owner_none_when_both_missing`
- `test_migration_pass_does_not_auto_reconcile`
- `test_cli_owner_reconcile_dry_run_apply_and_gate`
- `test_cli_show_and_list_display_effective_owner`

Run (from a checkout of this branch):

```bash
scripts/run_tests.sh tests/hermes_cli/test_kanban_owner_reconcile.py
```

## Post-deploy checklist

1. Deploy the release carrying the owner-writing INSERTs.
2. `hermes kanban owner-reconcile` (dry run) — confirm the candidate list.
3. `hermes kanban owner-reconcile --apply`.
4. Verify gate + zero remaining window rows (commands above).
5. Spot-check `hermes kanban show <id>` shows `owner:` even for rows that were
   NULL (G3) — though after G4 those rows are owned, so G3 mainly covers
   rows whose creator is NULL too (display `-`) and any future NULL clears.

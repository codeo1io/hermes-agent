# NPS false-pass masking remediation — dispatch record

**Finding:** `f5067dbabedca71fbac75cf0` — `phase3.supervisor.continuity.supervisor-nps-false-pass-masking` (MEDIUM, OPEN)
**Run:** `9b9034174f7f421d869da6374c1f3a23` (hermes-agent-bound decision vehicle; stewardship contract `stc-9b9034174f7f421d869da6374c1f3a23`, single surface = this document, no code surfaces)
**Date:** 2026-11-27 · **Authorship:** brainstorm `c5d70e69…`, plan `c50c60266…`, stewardship `55bc0c48…`, implement-1 `2e9743a0…` (all delegate attempts of this run)

This document is the durable in-repo record of a cross-repo remediation decision. It is
the ONLY surface this run is permitted to change (stewardship contract; supervisor
decision recorded in the stewardship phase). No hermes-agent source, test, or
configuration file may be touched by this run — the remediation code belongs to
other repositories and is dispatched as new runs (see §2).

## Task registry (lane split)

The planned change decomposes into eight task items. implement-1 authors the
odd-numbered items fully; implement-2 authors the even-numbered items into the
placeholders below. Content authority for every item is the plan artifact:
`/home/agent/.hermes/conductor-delegate-spool-maestro/c50c60266de94c59a59b5c36ea50c0f5-plan-supervisor-nps-false-pass-masking-f5067dba.md`.

| # | Task item | Lane |
|---|---|---|
| 1 | Decision record: verified root-cause chain + misattribution | implement-1 |
| 2 | Routing decision & run dispositions (supervisor decision) | implement-2 |
| 3 | Track O operational brief (unstick / re-attribute / sweep) | implement-1 |
| 4 | Track HC hermes-conductor remediation brief (HC-U1/U2/U3) | implement-2 |
| 5 | Track M maestro remediation brief (M-U1/M-U2) | implement-1 |
| 6 | This run's constraints & fold expectations (doc-only, KTD13) | implement-2 |
| 7 | Evidence appendix: live facts, artifact channels, repro pointers | implement-1 |
| 8 | Acceptance criteria & sequencing for the re-created runs | implement-2 |

---

## 1. Decision record: verified root-cause chain (implement-1)

The Maestro no-progress supervisor (NPS) reported `state=OK / progression=PASS`
with 17–19 dwell resets, 19–21 `pass_coalesced` frames, and zero actions or
escalations per 30 s cycle while run `c270c06e01c74249b8bc0812719c0b95` sat
durably stuck (`awaiting_evidence`, stale independent_review attempt ~43 ks, 8
unlanded-work rows). Every link below was verified live on 2026-11-27 against
code and fleet databases:

1. **The masked truth.** `c270c06e` executed its whole phase chain
   (independent_review seq 17 failed 2026-11-26T20:45Z; implement-1/2,
   targeted_tests, final_validation ×2, commit, push, pr, ci, reconcile all
   SUCCEEDED, reconcile at 2026-11-27T07:04:34Z). It then parked with
   `next_action_id` NULL, `status='awaiting_evidence'`, and **12 work_units all
   `lifecycle_fact='dispatched'` — never landed** (14 work_receipts were minted;
   receipts exist but landing/completion never fires).
2. **Bookkeeping keeps the corpse warm.** The conductor's periodic reconcile
   rewrites `runs.updated_at`/`runs.last_reconciled_at` every few minutes
   forever (observed 17:40 → 17:45 with no attempt in between;
   `engine.reconcile` → `store.save_run`).
3. **The census calls bookkeeping "durable progress".**
   `hermes-conductor/src/hermes_conductor/run_ownership.py:427-449
   _last_durable_progress()` = max(`runs.updated_at`, attempt
   updated_at/dispatched_at, MAX(attempts.updated_at),
   `scheduler_state.updated_at`/`last_decision_at`). The first and last of
   those are bookkeeping/liveness, not owner progress — so every reconcile
   touch advances `last_durable_progress` in the `conductor ownership --json`
   census that maestro consumes.
4. **Maestro's NPS consumes that signal as owner progress — three stacked
   masking layers:**
   - dwell reset: `maestro/src/maestro/daemon.py` (~:400) —
     `frame.last_durable_progress` > ledger `last_owner_progress_at` ⇒
     `reset_dwell("owner durable progress advanced")` (the 17–19 resets/cycle);
   - stall clock: `maestro/src/maestro/noprogress/classify.py:266
     _clock_last_progress = _clock_max(last_durable_progress,
     frame.updated_at)` — the awaiting-evidence-stall clock includes the
     bookkeeping-refreshed `updated_at`, so the 21 600 s budget never accrues;
   - hold: `classify.py:180-190 _hold_advancing_progress` — even past budget,
     any `last_durable_progress` bump holds the verdict.
   Net: PASS → `pass_coalesced` → zero escalations. The budgets were adequate;
   the clock, not the budget, is broken.
5. **Misattribution.** The finding's `root_cause_repo=hermes-agent` came from
   the LLM continuity auditor's `suspected_root_cause_repository` suspicion
   (`maestro/src/maestro/supervisor/continuity_audit.py`) — no hermes-agent
   surface participates in the masking chain (links 2–4 are hermes-conductor +
   maestro code). The fix belongs in **hermes-conductor** (primary) and
   **maestro** (secondary).

## 2. Routing decision & run dispositions (implement-2 — placeholder)

> **[implement-2]** Transcribe from plan §0/§4 + stewardship
> `delegate/55bc0c48ed374d5f9fad1bc5d5a81a8d.json`: the supervisor decision
> (supersede this run + re-create the remediation as hermes-conductor and
> maestro runs), this run's doc-only disposition if the supersede has not
> landed by implement time, and the must_remain_separate contract (HC run vs
> M run; no hermes-agent source changes from this run).

## 3. Track O — operational brief (implement-1)

Immediate, no code, executable by the operator or the conductor's documented
recovery surfaces. Evidence for every item is in §7.

- **O-1 Unstick `c270c06e01c74249b8bc0812719c0b95`.** Drive it to a terminal
  state via the conductor CLI recovery surface (supersede/complete — NEVER
  hand-edit the database; hand edits corrupt ledger truth). Record what closed
  it — that record is first evidence for HC-U3.
- **O-2 Re-attribute the finding.** `f5067dbabedca71fbac75cf0`
  `root_cause_repo`: `hermes-agent` → `hermes-conductor` (maestro findings
  update path). The misattribution source (uncorroborated auditor suspicion
  steering run repo selection) is a separate structural follow-up — see §8.
- **O-3 Fleet sweep.** Read-only, one indexed query per fleet DB, count of the
  bookkeeping-alive-but-done class:
  `SELECT id, status, updated_at, last_reconciled_at FROM runs WHERE
  status='awaiting_evidence' AND next_action_id IS NULL AND NOT EXISTS (SELECT
  1 FROM attempts WHERE attempts.run_id = runs.id AND attempts.status='open')`.
  Feed the count to the HC run's regression tests.

## 4. Track HC — hermes-conductor remediation brief (implement-2 — placeholder)

> **[implement-2]** Transcribe HC-U1 (owner-progress truth column
> `runs.last_owner_progress_at` stamped only on real transitions — discipline
> precedent `integration_queue.last_durable_progress_at`, store.py:1602;
> census predicate excludes `runs.updated_at`/`last_reconciled_at`/scheduler
> defer stamps; migration backfill from terminal attempts; consumer audit),
> HC-U2 (additive census field `owner_progress_age_seconds`; row schema
> string must stay `conductor.run-ownership/v1` or maestro drops the rows),
> HC-U3 (completion-boundary repair, root-cause-first; repro c270c06e; leads:
> review-cycle `state=findings` re-fire, native mission-gate outcome oracle
> "delegation terminal failed", completion_delivery_ledger), with tests,
> validation and KTD13 expectations — from plan §2.

## 5. Track M — maestro remediation brief (implement-1)

- **M-U1 — clock-free "no-live-work park" NPS contract** (deployable now,
  independent of HC). New `NPSContract` in
  `maestro/src/maestro/noprogress/classify.py`:
  entry = `status='awaiting_evidence'` AND `active_attempt is None` AND
  `next_action_id` is NULL — evidence-parked with no live work, stalled by
  construction; `budget_key=None` (escalate-only) or tier 1 with a short
  budget — **no dwell clock that bookkeeping can reset**. Stalled verdicts
  ride the existing `ProbeResult(root_cause_repo="hermes-conductor")` →
  finding → D3 path. Preserve the pass-coalescing write discipline
  (2026-10-04 85 MB → 2 GB row-regrowth lesson): FAIL trails keep full insert
  semantics; this contract never coalesces.
  Golden test: replay the 08:04–08:37 audit evidence shape (frames with
  bookkeeping-refreshed `updated_at`, no open attempt, stale prior attempt,
  unlanded units) — the verdict must be CLASSIFIED (escalated), never
  PASS/TRACKING. This one test would have caught c270c06e within one 30 s
  cycle.
- **M-U2 — clock/hold/reset truth gating** (lands AFTER HC-U1/HC-U2, which
  supply the truthful signal):
  1. `_clock_last_progress` drops `frame.updated_at`; a frame with no
     owner-progress clock must not fall to TRACKING-forever (the no-open-
     attempt shape is M-U1's until HC-U2 supplies a terminal-attempt
     fallback field);
  2. `_hold_advancing_progress` holds only on verified owner-progress-class
     advance (the HC-U2 typed signal), never any `last_durable_progress` bump;
  3. the daemon dwell reset gets the same gate;
  4. the corroborated `capacity-blocked` hold stays intact so the truth fix
     cannot over-escalate genuinely capacity-deferred runs (fresh scheduler
     reads only — KTD5).
  Tests per layer: bookkeeping bump does not reset/hold; real transition does;
  capacity-blocked still holds; SOURCE-STALE/SOURCE-DEGRADED semantics
  unchanged (finding 46b4abf1's U1/U4 contracts stay intact).

## 6. This run's constraints & fold expectations (implement-2 — placeholder)

> **[implement-2]** Transcribe from plan §4 + stewardship decision: doc-only
> delta (`changed_surfaces` = [this file] and nothing else; engine-derived
> tree delta must show exactly this file); no executable surface touched
> (validation scope `none`, risk_class `low`); commit/push/pr ship the doc on
> a conductor branch; the remediation code NEVER lands in this repo.

## 7. Evidence appendix (implement-1)

Live-verified 2026-11-27 (read-only queries + source reads):

- **Databases:** `runs`/`attempts`/`work_units` rows for `c270c06e` in
  `/home/agent/.hermes/conductor-gateway/maestro-engineering.db` (updated_at ==
  last_reconciled_at advancing with zero attempts since 07:04:34Z; 12 units
  `dispatched`; independent_review seq 2 outcome records the review-cycle
  `state=findings` re-fire; seq 17 outcome: "native authority gate: delegation
  failed; delegation terminal failed"). Finding row in
  `/home/agent/.local/state/maestro/maestro.db`.
- **Code:** `run_ownership.py:427-449`; `daemon.py:390-500` (dwell reset +
  pass_coalesced); `noprogress/classify.py:140/:180-190/:266` + contracts
  table; `noprogress/evidence.py:679` (frame build);
  `supervisor/continuity_audit.py` (auditor prompt);
  `stewardship/policy.py:204-215` (the ≥1-change-unit gate that forced this
  run's doc-only disposition).
- **Delegate artifact channels (authoritative):**
  - brainstorm: `…/conductor-delegate-spool-maestro/c5d70e69aebc401d81dc04c97cf8db4e-brainstorm-supervisor-nps-false-pass-masking-f5067dba.md`
  - plan: `…/conductor-delegate-spool-maestro/c50c60266de94c59a59b5c36ea50c0f5-plan-supervisor-nps-false-pass-masking-f5067dba.md`
  - stewardship decision: `…/conductor-delegate-spool-maestro/delegate/55bc0c48ed374d5f9fad1bc5d5a81a8d.json`
  - implement-1 (this lane): `…/conductor-delegate-spool-maestro/delegate/2e9743a0bb1441dea3c80b1fa696474f.json`
- **Repro pointer for the re-created runs:** c270c06e is the live instance of
  the masked nonconvergence; its estate
  (`conductor-worktrees/hermes-roadmap-7b71888687/run-c270c06e01c7-c270c06e`)
  and its mission binding (`msn-8d111fc83cfff9420745`, plan_status draft) are
  the first places HC-U3's root-cause pass should look.

## 8. Acceptance criteria & sequencing (implement-2 — placeholder)

> **[implement-2]** Transcribe from plan §5/§7: sequencing graph (O now; M-U1
> parallel-now; HC-U1 → HC-U2 → M-U2; HC-U3 independent), the per-unit
> verification matrix, risks (consumer regressions, over-escalation,
> schema-string mismatch, KTD13 empty-list semantics, row-regrowth), and the
> audit-corroboration follow-up (suspected_root_cause_repository gate before
> it steers run repo selection).

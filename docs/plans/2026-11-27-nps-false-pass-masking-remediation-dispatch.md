# NPS false-pass masking remediation — dispatch record

**Finding:** `f5067dbabedca71fbac75cf0` — `phase3.supervisor.continuity.supervisor-nps-false-pass-masking` (MEDIUM, OPEN)
**Run:** `9b9034174f7f421d869da6374c1f3a23` (hermes-agent-bound decision vehicle; stewardship contract `stc-9b9034174f7f421d869da6374c1f3a23`, single surface = this document, no code surfaces)
**Date:** 2026-11-27 · **Authorship:** brainstorm `c5d70e69…`, plan `c50c60266…`, stewardship `55bc0c48…`, implement-1 `2e9743a0…`, implement-2 `6165453f…` (all delegate attempts of this run)

This document is the durable in-repo record of a cross-repo remediation decision. It is
the ONLY surface this run is permitted to change (stewardship contract; supervisor
decision recorded in the stewardship phase). No hermes-agent source, test, or
configuration file may be touched by this run — the remediation code belongs to
other repositories and is dispatched as new runs (see §2).

## Task registry (lane split)

The planned change decomposes into eight task items. implement-1 authored the
odd-numbered items fully; implement-2 authored the even-numbered items into
the same document (all eight items are complete). Content authority for every item is the plan artifact:
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

## 2. Routing decision & run dispositions (implement-2)

**Supervisor decision (stewardship phase, 2026-11-27):** supersede this run
and re-create the remediation as hermes-conductor (+ maestro) runs from the
folded plan; the stewardship phase nonetheless returned a minimal VALID
request (this single doc surface) so the run would not be left as a
c270c06e-style `awaiting_evidence` zombie while the supersede lands.

**Why the decision was forced (gate bind, fold-code-verified):** the
stewardship gate cannot express the plan's zero-delta disposition —
`repositories` must resolve against the run's own anchored set
(`spool_outcomes.py anchored_repository_candidates`: campaign → canonical →
workspace; this run anchors to hermes-agent only — conductor/maestro paths
are structurally rejected as unanchored), and `validate_contract` requires
≥1 change unit (`stewardship/policy.py:204-215`, "contract must declare at
least one ChangeUnit"), so a no-surface request cannot fold. Any
hermes-agent surface set for the actual remediation would be fabricated
work.

**Disposition as executed:** the supersede had NOT landed by implement time
(run still `running`, next action `implement:implement-2` at 19:13Z), so the
implement lanes execute the supervisor's fallback verbatim: author ONLY
this document — no code, no other files. If the supersede lands
mid-ladder, this record is pointer-complete: every brief's content
authority is the spool plan artifact (§7).

**Separation contract (stewardship `must_remain_separate`):**
1. The hermes-conductor remediation run (Track HC) and the maestro
   remediation run (Track M) ride SEPARATE runs and separate landing PRs —
   different repositories, different ownership, no cross-pollination.
2. This dispatch-record document and any hermes-agent source code: this run
   may never change source, tests, or configuration in this repository.

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

## 4. Track HC — hermes-conductor remediation brief (implement-2)

New run against `/work/projects/hermes-conductor` (this section is its
authoritative brief; plan §2 is the long form).

**HC-U1 — owner-progress truth column + census predicate fix.** Targets:
`run_ownership.py:427-449` (`_last_durable_progress`), `store.py` (runs
schema + save paths), `engine.py` (transition stamping).
1. Add `runs.last_owner_progress_at` (TEXT ISO), stamped ONLY on real owner
   transitions: attempt dispatch→terminal, phase-result fold, work-receipt
   mint, blocker mint/clear, run status transition. In-repo discipline
   precedent: `integration_queue.last_durable_progress_at` (store.py:1602
   "stamped only by real transitions"; integration.py:1048/1073).
2. `_last_durable_progress` reads the new column (migration fallback: MAX
   over TERMINAL attempts' `updated_at`). EXCLUDE `runs.updated_at`,
   `runs.last_reconciled_at`, and `scheduler_state.updated_at/
   last_decision_at` from the progress projection — bookkeeping/liveness,
   not progress.
3. Backfill (one bounded pass, indexed run_id lookups):
   `UPDATE runs SET last_owner_progress_at = (SELECT MAX(updated_at) FROM
   attempts WHERE run_id = runs.id AND status IN ('succeeded','failed',
   'superseded'))`.
4. Consumer audit (in-unit, blocking): every reader of census
   `last_durable_progress` — maestro `noprogress/evidence.py:679`, conductor
   `just_works.py:799`, `application.py:284/880`, and run_ownership's own
   `_resource_wait_holder_liveness` (T4) — re-derived against the new
   semantics before the predicate switches.

Tests (behaviour contracts): reconcile/bookkeeping touch with no attempt
transition does NOT advance the census clock (the exact c270c06e shape);
scheduler defer does NOT advance; attempt terminal DOES; receipt mint DOES;
census projection golden (a parked done run ages in hours, not minutes).

**HC-U2 — typed census signal.** Additive `owner_progress_age_seconds` on
the `conductor.run-ownership/v1` row, distinct from `updated_at`. Constraint:
maestro's `collect_ownership_census` drops rows whose schema string differs
from `conductor.run-ownership/v1` — the additive field must NOT bump the row
schema string; a parse test runs against the exact maestro consumer shape.

**HC-U3 — completion-boundary landing repair (root-cause-first).** Repro:
c270c06e — every attempt terminal, reconcile SUCCEEDED, 14 work_receipts
minted, yet 12 work_units stuck `lifecycle_fact='dispatched'`,
`next_action_id` NULL, `awaiting_evidence` forever. Investigation order:
(1) unit lifecycle advancement — who moves a unit dispatched → landed, and
why doesn't a minted receipt advance it (`engine.reconcile` →
`mint_phase_receipts` → `promote`); (2) review-cycle state machine — the
run's own independent_review seq 2 outcome records "the engine had folded my
first review but left the review cycle in state=findings (implementation
unknown) and re-fired 60 seconds later"; (3) native mission-gate outcome
oracle — `mission_authority` G4 ("plan-linked envelopes fold only through
the native oracle: delegation-terminal + contract SATISFIED") with seq 17
"native authority gate: delegation failed; delegation terminal failed";
check `plan_outcome_sweep_fold_decision` and `completion_delivery_ledger`
rows for c270c06e. Fix invariant: all attempts terminal + receipts minted +
next_action NULL ⇒ the run reaches a terminal state within one reconcile
pass (complete, or fail with a typed blocker — never `awaiting_evidence`
forever). Validation: scoped pytest (ownership/reconcile/closeout) + the
new regression contracts.

**KTD13 for the HC run:** declare every touched file in
`validation_evidence.changed_surfaces` (repo-relative) — expected ≈
`src/hermes_conductor/run_ownership.py`, `store.py`, `engine.py`, the
mission-gate locus, plus new test files.

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

## 6. This run's constraints & fold expectations (implement-2)

- **Doc-only delta.** `validation_evidence.changed_surfaces` = [this file]
  and nothing else, for BOTH implement lanes: implement-1 authored the file
  (checkpointed by the engine as commit `f0a4b9a9b66` "conductor checkpoint:
  9b9034174f7f integration"); implement-2 modified it in place (this
  attempt). The engine-derived tree delta must show exactly this one file —
  any other tree change violates the stewardship contract.
- **No executable surface touched:** validation scope `none`, risk_class
  `low`; no validation digest (the work order carried no validation block,
  and no executable surface changed).
- **Landing:** commit/push/pr phases ship the doc on the conductor branch
  (`conductor/run-9b9034174f7f`); the PR is an operator-review vehicle for
  the dispatch record. The remediation code NEVER lands in this repository.
- **Downstream gates:** targeted_tests/full_tests treat this as a docs-only
  delta (digest inspection, no test scope); independent_review verifies the
  delta matches the contract's single surface and the no-code separation
  constraint.
- **KTD13 semantics:** never declare an empty `changed_surfaces` list over a
  non-zero delta — here the single doc surface is declared exactly, in both
  lanes' phase results.

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

## 8. Acceptance criteria & sequencing (implement-2)

**Sequencing:**

```
O-1/O-2/O-3 (now, no code)  ──►  evidence feeds HC-U3's tests
M-U1 (now, independent)     ──►  catches the masked class immediately
HC-U1  ──►  HC-U2  ──►  M-U2          (typed signal before clock gating)
HC-U3 (independent of HC-U1/U2; needs its own root-cause pass)
```

**Verification matrix:**

| Unit | Verification |
|---|---|
| HC-U1 | 4 behaviour tests + census golden; scoped pytest green |
| HC-U2 | additive-diff + maestro-consumer parse test |
| HC-U3 | synthetic done-run reaches terminal in one reconcile; c270c06e-shaped regression |
| M-U1 | golden replay of the 08:04–08:37 shape escalates |
| M-U2 | per-layer truth tests; capacity hold intact; 46b4abf1 semantics unchanged |
| O-1/2/3 | run terminal + finding re-attributed + sweep count recorded |
| this run | worktree delta == exactly this document, both lanes |

**Risks & mitigations:** census consumer regressions (HC-U1 consumer audit
before the predicate switches); over-escalation of capacity-deferred runs
(corroborated `capacity-blocked` hold kept intact — fresh scheduler reads
only, KTD5); census schema-string mismatch silently dropping rows
(additive-only change + parse test); KTD13 empty-list semantics (never []
over a non-zero delta); row-regrowth recurrence (new contract inserts on
first detection only, coalescing discipline preserved); c270c06e must never
be completed by hand — DB hand-edits corrupt ledger truth (conductor CLI
recovery surface only).

**Structural follow-up (kept OUT of these runs by design):** a
corroborated gate on the continuity audit's `suspected_root_cause_repository`
before it steers remediation-run repo selection — this misattribution
(f5067dba → hermes-agent) cost this run its scope and forced the re-route
recorded in §2.

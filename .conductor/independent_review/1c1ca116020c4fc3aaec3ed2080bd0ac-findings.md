# Independent review round 3 — attempt `1c1ca116020c4fc3aaec3ed2080bd0ac` (2026-10-19)

**VERDICT: NEEDS_CHANGES** — one new high finding (F2) on the rm-028 unit; every previously
open finding (F0, F1 and the original eight) is verified fixed on the current tree.

Review target: the cycle-1 batch (5 change-units, 11 tracked paths) at HEAD `c4da06121c8c8`
plus working-tree delta, the reconstructed compound learnings, the ROADMAP.md status updates,
and the F0 CI-record correction — reviewed adversarially with fresh probes, not by re-reading
prior attempts' notes.

## Tree integrity (this attempt, live)

- Engine digest re-derived: `validation:v1:d534a23bbce565b90299520fe594e8d276a9d3650cb46f9417d9daf9f4619219` — byte-identical to the fix-phase/dispatch digest recorded by attempts 535eff→d0a066ce and re-verified by f578abde.
- All 11 batch paths `cmp`-identical to CI head `895065763f3ae0451013eb17349ff46da4ff1f02` (ephemeral PR #103 head); every mtime is the c22cc4d4 03:28 restore — the reaped attempts 222213bf/a94763e3/f578abde/1c4dabfa/a1e36783/9c90e10a left no tree drift.
- Porcelain: 18 paths, all sanctioned (9 M batch + ROADMAP + 2 new tests + 7 untracked .conductor); the 26 older .conductor files are TRACKED at HEAD (prior run eab787b4's merged artifacts — checkout-time mtimes), not drift.
- Dead-attempt forensics: 9c90e10a (18:50–19:10Z Oct 18) wrote no ledger, no envelope, no /tmp scratch in its window, no tracked-file mtime — nothing to adopt; 1c4dabfa died 32s in; a1e36783 dead-lettered pre-turn. This attempt redid the review from scratch.

## Independently verified SOUND

1. **F0 (high, false CI receipt) — fix re-verified live 2026-10-19.** Check-runs at the full 40-char head: `2 failure / 12 skipped / 20 success` (34 total) — failures are `Python tests / Run tests` (2026-09-29T15:33:56Z) and `All required checks pass` (15:34:04Z); PR #103 CLOSED; the recorded abbreviated-SHA query (`895065763f3f3a`) still returns HTTP 422 today. The correction artifact's three claims + true tally all reproduce.
2. **F1 (low, receipt anchoring) — fixed.** learnings rows now anchor each receipt to its exact head (`80f01ed` pre-fix = green 34/34; shipping head = 32/34 with the 2 reds named, "NOT a green receipt").
3. **rm-029 pin map.** All 15 pinned digests in `hermes_cli/local_runtime/binaries.py` match the upstream `ggml-org/llama.cpp` b10964 release digests byte-for-byte (live `gh api`, 27 assets with digests; the 12 unpinned are outside the shipped resolver matrix — android/s390x/sycl/openvino/opencl/win-cuda-12.4/ui/xcframework/cudart-12.4). `pinned_assets(tag)` applies by default; explicit `expected_sha256` still overrides.
4. **rm-030 launchd JXA port.** `launchd_program_arguments` is byte-identical to upstream `8682d5791b` (28/28 lines); exit-status translation (`signal===0 ? (status>>8)&255 : 128+signal`) is the standard WIFEXITED/WIFSIGNALED encoding; the website doc change matches the mechanism.
5. **rm-028 core closure.** 20-probe adversarial battery (mine, not the fixer's), run against BOTH the standalone-loaded HEAD base module and the fix tree: P0 `V='-exec rm {} ;'; find / $V` and 11 more primary shapes (prefix-assignment, `R=rm;F=-rf`, double-quoted assignment+ref, brace refs, newline/pipe separators, self-reference, subshell `( X=rm; $X … )` and `X=rm; ( $X … )`) all flagged on fix / unflagged on base; 7 benign variable uses all clean on both (no false-positive drift); documented residuals (env/export/+=/chained indirection/16-decoy cap) behave byte-identically on base and fix — no regression.
6. **Test + static evidence.** `scripts/run_tests.sh` over the 5 changed-surface test files: 346 passed / 0 failed / 2 skipped, exit 0, no FLAKY. `check_no_tmp_literals` clean, `check_compat_pointers` clean, `check_profile_scope_patterns` exit 0.
7. **Compound artifacts.** ROADMAP delta is status-only (+92/−9): implemented×4, half-implemented×1 with attempt ids, phantom-signal voids (rm-001/rm-002) justified, priorities re-scored; learnings reconstruction is honestly labeled and anchors every receipt.

## Open finding — F2 (high, P1): quoted command-word variable reference still bypasses the gate

- **file:line:** `tools/approval_detection.py:1490` (variant block; claim at `:1141`), test gap at `tests/tools/test_approval.py:2289`
- **Repro (fix tree):** `detect_dangerous_command('X=rm; "$X" -rf /')[:2]` → `(False, None)`; same for `X=rm; "${X}" -rf /`. The shell runs `rm -rf /` — an approval-free destructive delete.
- **Proof it is a gap, not a documented residual:** the projection substitutes correctly (`_expand_shell_variable_assignments` yields ` ; "rm" -rf /`) and that exact string, as a LITERAL command, IS flagged (`(True, 'delete in root path')`) — the literal pipeline's first variant `_grep_safe_detection_variant` resolves the quoted command word. The projection block (`:1490-1496`) yields only `_normalize_command_for_detection` + `_mark_command_starts` variants, omitting the grep-safe treatment, so the projected quoted command word never matches. Docstring `:1141` claims "later unquoted or double-quoted ``$NAME`` / ``${NAME}`` references" are substituted — the substitution happens, the detection drops it. Unquoted `$X` and brace `${X}` forms ARE flagged; `:2289-2290` pin quoted refs only in ARGUMENT position. The shape appears in neither the documented residual list (env/export/+=/chained/arrays/16-decoys) nor the 19 invariant tests.
- **Why high:** rm-028 is the cycle's p100 trust-boundary unit and its acceptance — "variable-built destructive words resolve before rule matching" — is falsified by a one-line spelling whose literal equivalent is caught. Narrower than the P0 (the plain default spelling is closed), so high, not critical.
- **Fix shape for the fix turn:** feed `expanded` through the same front half the literal gets — yield `_grep_safe_detection_variant(_normalize_command_for_detection(expanded))` (and its command-start-marked sibling) alongside the two current variants — and pin two red-on-current tests (`X=rm; "$X" -rf /`, `X=rm; "${X}" -rf /` → flagged) plus benign parity (`F=notes.txt; cat "$F"` stays clean).

## Residuals accepted as documented (no action)

`env X=y` forms, `export`/`+=` variants, chained indirection `X=$Y`, arrays, the 16-assignment cap — all documented in the learnings + ROADMAP, pinned by tests, base-equal behavior.

## Gating

F2 must be fixed with red-on-current tests before this batch ships. F0's deferred green-CI-head acquisition remains open as provisional work for the push-bearing phase; no artifact of this run may claim CI-green for head `895065763f3a` until a green head exists.

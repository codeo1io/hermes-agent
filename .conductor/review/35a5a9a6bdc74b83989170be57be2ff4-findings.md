# Independent adversarial review — cycle 2 batch (run b45c23b895be40c4a2e40ab9d55c1648, attempt 35a5a9a6bdc74b83989170be57be2ff4)

Target: uncommitted cycle-2 batch (rm-022, rm-021, rm-029, rm-028+rm-019, rm-032, stretch rm-030) + the
compound step's ROADMAP.md cycle-log/lessons/cycle-3-seeding updates, in worktree
conductor/run-b45c23b895be (base bcf55bbaed). Review method: in-thread adversarial pass (no subagents,
per delegate constraints); every claim re-derived from the tree, the preserved /tmp logs, and the
upstream git objects — not from the emissions' own words.

## VERDICT: APPROVE — batch is sound to ship; findings below are evidence-hygiene and acceptance-wording
issues, none blocking. Zero-regression verdict independently confirmed; security boundaries hold.

## Per-unit verification (all re-executed this review, 2026-09-22)

- rm-022 lockguard: port is byte-IDENTICAL to upstream 524041b9d0's post-fix file; our base was
  byte-identical to 524041b9d0^ (md5 9f4d5a80… both) — strongest port fidelity. Ported test byte-identical
  to upstream's. Live: 4 passed + 1 @pytest.mark.windows_only skip (proper marker). `supported()` gates
  the fallback correctly (fcntl=None → _F_OFD_SETLK=None → hold()/release() no-op).
- rm-021 credential collisions: single shared helper `duplicate_credential_lines` consumed by migrate
  preflight, doctor (`_check_profiles`), and `gateway status` — matches ed69aa9e6e end-state layout;
  our tree correctly never gains the intermediate 54817f463b profile_channels scanner (upstream post-state
  grep = 0, ours = 0; "reconciled rather than duplicated" is accurate). Security: output carries profile
  names + env-key NAMES only; `_credential_claims` keys (platform, fingerprint) never printed; test asserts
  secret absence. Live: 2 passed.
- rm-029 classifier seam: `_JS_RELEVANT_CONTRACT_FILES` names exactly the two Python sources the vitest
  mirror reads (relay-deliver-budget.test.ts:15-16 — verified, no third source missed); ci.yaml:105 gates
  js-tests on `frontend == 'true'` and detect exports classify's frontend (:45). Live: 74 passed incl. 2 new cases.
- rm-028+rm-019: sentinel `uses:` SHA 7d47ab484a937c5742ddcb3b69399495e8342beb independently re-verified ==
  current codeo1io/.github main (ls-remote); workflow_dispatch present; YAML parses; tree-wide
  `uses:.*@main` grep = 0 hits (re-run). plugin-validate snippet SHA 439eb0395e resolves; no rendered docs
  embed the snippet (grep website/ skills/ = 0), so regeneration is moot.
- rm-032: dead `as_exclusive_end` kwarg removed; sole other call site (:146) is positional — no stale
  kwarg call sites (grep). `_normalize_exclude_session_ids` tuple return has exactly one consumer (:602);
  note flows through `_discover(**note_kwargs)` → `_discover_payload(**extra)` → `_ok(**payload)` —
  signature-verified end to end. New tests are behavior contracts (cap hit ⇒ note present + past-cap id
  resurfaces; within-cap ⇒ no note + exclusion works). Live: 62 passed.
- rm-030: tips.md + team-telegram-assistant.md now teach config.yaml terminal.backend/docker_image (keys
  verified against config_defaults.py:307 / config.py:3579); the new "stale TERMINAL_ENV flips the backend
  mid-session" sentence is backed by env_loader.py's `_reapply_terminal_config_bridge` (#29186/#67323).
  Remaining TERMINAL_ENV mentions are the warning itself + the env-var reference table — no .env
  recommendation remains.

## Batch-level evidence verification

- Full-suite logs re-read: Summary 4174 files / 48819 passed / 33 failed / 387 skipped in 2664.9s ✓;
  33 unique FAILED ids ✓; 27 failing files ✓; base A/B 27 files → 18 failed ✓; batch-solo 12 files →
  1 failed (honcho) ✓. 33 = 18 deterministic + 14 flakes + 1 order flake ✓. Zero batch-surface failures ✓.
- Validation digest re-derived NOW: validation:v1:8a1794332c548d2c9835218dd68ecfbb3cd521f91661c38267bb1567bd1030a5
  == dispatch digest (tree byte-identical through implement/test/compound/review; review modified no tracked file).
- Compound additions-only proof re-verified: /tmp/ROADMAP.pre-compound.md md5 038eaaf49e9bc479c9a398135d7a7800
  @ 29,698 bytes; head -c 29698 ROADMAP.md reproduces it; 265 lines; git diff ROADMAP.md = 109(+)/0(-); 32 rm-ids unchanged.
- Diff arithmetic consistent: implement 262(+) + compound 25 = current 287().

## FINDINGS

1. MEDIUM — ROADMAP.md:258 (cycle-2 lessons): the "deterministic set clusters" enumeration mislabels 12
   pass-solo LOAD FLAKES as deterministic (delegate_capacity_interrupt ×3, zombie_process_cleanup,
   tui_gateway ×3, moa_loop_mode, pi_rpc_client, sequential_tool_interrupt, session_hygiene,
   transcription_tools — every one is in /tmp/flaky_candidate_files.txt and absent from the base-failing
   set), omits the genuinely deterministic tests/tools/test_delegate.py::test_mixed_composite_is_subtracted_at_child_assembly,
   and drops profiles_sidebar_cache + relay_shared_metrics from the accounting; enumerated total 29 ≠ 18.
   The zero-regression VERDICT is unaffected (A/B evidence is correct), but the durable lesson is wrong in
   detail and ROADMAP.md:262 seeds cycle 3 with the error ("delegation-lifecycle cluster … 5 tests" is
   really 2 deterministic + 3 flakes). Cycle 3 must re-derive the deterministic set from
   /tmp/base_ab_868ed09a.log, not from this lesson.
2. LOW — ROADMAP.md:171 (rm-021 acceptance) vs hermes_cli/gateway.py:6385: acceptance says "detected at
   gateway serve time"; the port (faithful to upstream 54817f463b + ed69aa9e6e, which also never wired a
   serve-time check) surfaces only via `gateway status` and doctor. The compound log words this accurately
   ("gateway-status consumers wired"). Resolve next cycle via additions-only acceptance correction or a
   serve-time surfacing unit.
3. LOW — .github/workflows/private-leak-sentinel.yml:21: `# v1` cites a tag that does not exist —
   codeo1io/.github publishes no tags (ls-remote --tags empty). SHA itself verified current. Per the
   SHA + `# vN` policy the comment should reference a real tag or state commit provenance.
4. LOW — .github/actions/plugin-validate/action.yml:8: `# v2026.9` is a series label, not a tag pin —
   439eb0395e is not any v2026.9.x tag target (v2026.9.14 → 345cd2b057, v2026.9.21 → d337b736aa1); upstream
   main has moved to c3021aff0d since the research phase.
5. LOW — ROADMAP.md:246 (rm-022 log entry): claims "7 passed / 1 windows_only skip"; the file has 3 test
   functions → actual 4 passed + 1 skip (live-verified; the targeted_tests emission said 4✓ correctly).
   Evidence-count inaccuracy only.
6. INFO — website/docs/reference/environment-variables.md:250 (+ zh-Hans mirror :192): TERMINAL_ENV row
   remains without a "legacy; prefer config.yaml terminal.backend" annotation. Outside rm-030's tips.md
   acceptance scope and the row is not false (config.py:2016 still reads it), but it is the same drift
   class — candidate for a next-cycle doc pass.

## Security / durability boundary checks (all pass)

- No credential value, hash, or fingerprint reaches any output surface (code + test verified).
- Supply chain: both `uses:` pins SHA-pinned and resolve to real commits; tree-wide mutable-ref audit = 0.
- No new HERMES_* env vars, no telemetry, no cache-surface mutation (batch touches no prompt/session-cache path).
- Durability: lockguard fallback disables the guard (no-op) instead of raising — matches module contract
  "No-op on Windows and on runtimes without OFD locks"; migration blocker semantics preserved (default-first
  claim ordering kept in `_check_duplicate_credentials`).
- Repo conventions: new tests use temp HERMES_HOME + Path.home patch; marker (not bare skipif) for the
  Windows-only test; placement mirrors source tree; no change-detector tests added.

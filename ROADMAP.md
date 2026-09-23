# hermes-agent — Roadmap

> Autonomously maintained by the roadmap sync (reliability-first). Items cite reproducible codebase signals; acceptance is proven by cited evidence.

**Vision**: A reliable, customer-friendly repository advanced by evidence-cited roadmap cycles owned by the autonomy loop

**Pillars**: reliability work outranks customer-experience work; every roadmap item cites reproducible codebase signals; acceptance is proven by cited evidence, never claimed

## Fleet context

- dependents (changes here affect): (host), dashboard, hermes-infra, hermes-stewardship-dashboard, jarvis, magic-hermes
- graph: evidence-derived (imports/refs/deploy surfaces); advisory

## Open items

### Add test coverage for 21 untested module(s)
- id: `rm-002` | track: reliability | priority: 100.0 | status: candidate
- signals: reliability.no_tests:*, reliability.no_tests:.github/scripts/run-workspace-checks.mjs, reliability.no_tests:.worktrees/t_3143b8b5/.github/scripts/run-workspace-checks.mjs, reliability.no_tests:.worktrees/t_3143b8b5/agent/api_error_summary.py, reliability.no_tests:.worktrees/t_3143b8b5/agent/api_request_hooks.py (+16 more)
- acceptance: Every module in ['*', '.github/scripts/run-workspace-checks.mjs', '.worktrees/t_3143b8b5/.github/scripts/run-workspace-checks.mjs', '.worktrees/t_3143b8b5/agent/api_error_summary.py', '.worktrees/t_3143b8b5/agent/api_request_hooks.py', '.worktrees/t_3143b8b5/agent/auxiliary_health.py', '.worktrees/t_3143b8b5/agent/auxiliary_wire.py', '.worktrees/t_3143b8b5/agent/chat_completion_helpers_relay.py', '.worktrees/t_3143b8b5/agent/chat_completion_stream_monitor.py', '.worktrees/t_3143b8b5/agent/compression_facade.py', '.worktrees/t_3143b8b5/agent/credential_pool_admin.py', '.worktrees/t_3143b8b5/agent/credential_pool_model_cooldowns.py', '.worktrees/t_3143b8b5/agent/lazy_forward.py', '.worktrees/t_3143b8b5/agent/reasoning_params.py', '.worktrees/t_3143b8b5/agent/terminal_approval_batch.py', '.worktrees/t_3143b8b5/agent/transcript_repair.py', '.worktrees/t_3143b8b5/agent/turn_empty_response.py', '.worktrees/t_3143b8b5/agent/turn_preflight_gate.py', '.worktrees/t_3143b8b5/agent/turn_response_intake.py', '.worktrees/t_3143b8b5/agent/turn_stop_gates.py', '.worktrees/t_3143b8b5/agent/turn_tool_round.py'] has a corresponding test file with at least one passing test
- evidence: CI: pytest collects the new test files and they pass

### Refactor 21 high-complexity function(s)
- id: `rm-001` | track: reliability | priority: 90.0 | status: candidate
- signals: reliability.complexity_hot:*, reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1, reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1, reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1, reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1 (+16 more)
- acceptance: Each flagged function is decomposed below the branch threshold with behavior locked by characterization tests
- evidence: ast-based branch-count check passes in CI

### Refresh stale top-level documentation
- id: `rm-003` | track: reliability | priority: 43.0 | status: candidate
- signals: reliability.stale_doc:README.md
- acceptance: Docs regenerated/updated; staleness detector reports 0 signals
- evidence: inference.stale_docs returns [] for the repo

### Sync the plugin catalog from upstream (127 add-only entries)
- id: `rm-004` | track: customer-experience | priority: 48.0 | status: candidate
- signals: research.upstream_gap:plugin-catalog/ — upstream 1baae3132a carries 137 YAML entries, this tree 10 (all 10 shared; 127 absent, e.g. Search1API, OpenAlex research tools, kiro-acp, junie-acp, brave-search, hermes-security-audit, artifact-relay, Prism)
- acceptance: Every upstream plugin-catalog YAML as of 1baae3132a exists verbatim in plugin-catalog/ (count parity 137=137, our 10 divergent entries preserved); plugin-catalog CI validation green; a catalog-listing smoke test shows a newly synced entry
- evidence: git diff plugin-catalog/ (additions only); plugin-catalog-ci lane run

### Add session_search time bounds and session exclusion
- id: `rm-005` | track: customer-experience | priority: 44.0 | status: candidate
- signals: research.upstream_gap:tools/session_search_tool.py — no after/before/exclude_session_ids parameters (upstream 5655920f9a has them)
- acceptance: Tool schema carries after/before/exclude_session_ids; FTS recall respects bounds (inclusive semantics pinned by tests) and excludes listed sessions; date-scoped recall proven by an E2E test against a temp session DB
- evidence: pytest tests/tools/test_session_search* covering bounds + exclusion; upstream 5655920f9a as port reference

### Port skills.auto_load from upstream
- id: `rm-006` | track: customer-experience | priority: 36.0 | status: candidate
- signals: research.upstream_gap:skills auto-load — no auto_load config anywhere (upstream 1976869c01 pins skills into every new session's prompt)
- acceptance: config.skills.auto_load (default off) pins listed skills into new sessions' prompts; with the config unchanged the system prompt stays byte-stable across turns (prompt-caching invariant); enabling is documented as next-session-effective per the cache-aware slash-command convention
- evidence: pytest asserting pinned-skill presence per new session + byte-stability guard; upstream 1976869c01 as reference

### Parameterize the native vision embed budget
- id: `rm-007` | track: customer-experience | priority: 24.0 | status: candidate
- signals: research.upstream_gap:vision embed budget hardcoded — no embed_target_bytes config (upstream f37336522b replaces the 256 KB budget)
- acceptance: vision.embed_target_bytes config (default = current behavior) replaces the hardcoded budget; override proven by test
- evidence: pytest on the config path; upstream f37336522b as reference

### Refresh video generation model families
- id: `rm-008` | track: customer-experience | priority: 22.0 | status: candidate
- signals: research.upstream_gap:plugins/video_gen/fal/__init__.py — declares ltx-2.3/kling-v3 only; upstream 37286d3064 adds LTX 2.5 + Kling O3 and bumps Happy Horse v1.1
- acceptance: New families listed with correct tier/pricing/audio metadata and reachable via the video_gen tool; no existing family removed
- evidence: catalog assertion tests (contract, not snapshot) + tool smoke test

### Auto-install catalog-listed memory providers named in config
- id: `rm-009` | track: customer-experience | priority: 34.0 | status: candidate
- signals: research.upstream_gap:hermes_cli/memory_setup.py — no catalog wiring (upstream e21ccdd7dc installs a configured provider that left core from the catalog); pairs with rm-004
- acceptance: A config naming a catalog-listed but unimportable memory provider resolves via plugin-catalog, installs, and passes doctor validation; failure path leaves a clear actionable message
- evidence: E2E test with temp HERMES_HOME exercising the real install chain; upstream e21ccdd7dc as reference

### Add the Blender MCP bridge and backend-local app discovery
- id: `rm-010` | track: customer-experience | priority: 26.0 | status: candidate
- signals: research.upstream_gap:optional-mcps/ — 65 entries, no blender (upstream 12f495feac adds the Blender bridge, a38d544f1b optional backend-local app discovery)
- acceptance: Blender bridge installable from the catalog and functional against a stub MCP server; app discovery is opt-in and does not probe when disabled
- evidence: install smoke test + discovery-off default asserted

### Decide gateway.multiplex_profiles default (upstream flipped to on)
- id: `rm-011` | track: customer-experience | priority: 20.0 | status: candidate
- signals: research.divergence:gateway/config.py:545 multiplex_profiles defaults False; upstream a10bbf95bb defaults True gated by a boot-time serve guard
- acceptance: Decision recorded (keep-off or flip) with rationale; if flipped, a boot-time serve guard prevents conflicting multiplex serving and migration is documented
- evidence: config default test + guard test; ADR-style note in the PR description

### Port the upstream compression/loop hardening family
- id: `rm-012` | track: reliability | priority: 72.0 | status: candidate
- signals: research.upstream_fixes:agent loop — context rejection no longer mislabeled "conversation too long" (5e95050608); review input budget derived from resolved context window + capped (a6ad3cc3ff, f797a23c09); snapshot grounding dedupes task sections / replaces alias headings (dbf19a6cfa, d295ef02ee); our agent/context_compressor.py carries '## Active Task' machinery without these fixes
- acceptance: Hunk-level content diff confirms which fixes are missing; each missing fix ported with a regression test proving the symptom on base (unexplained server context rejection not mislabeled; review budget bounded; duplicate task sections collapsed)
- evidence: tests/agent/ regression tests + port notes citing upstream SHAs

### Upgrade provider/protocol SDKs behind provider lanes
- id: `rm-013` | track: reliability | priority: 64.0 | status: candidate
- signals: research.dep_lag:anthropic 0.87.0→1.7.0 (major), openai 2.24.0→3.16.2 (major), mcp 2.0.0→2.2.0, agent-client-protocol 0.9.0→0.12.1 (ACP schema v1.23.0, 2026-09-18; acp_adapter/server.py:509 delegates to acp.PROTOCOL_VERSION)
- acceptance: Each SDK bumped with repo upper bounds and its provider lane green (anthropic, openai-compatible, mcp client/server, acp adapter round-trip); breaking-change migration notes in the PR
- evidence: uv.lock diff + per-lane CI runs; PyPI versions cited in the PR

### Refresh CI supply-chain tooling (uv pylock, osv-scanner 2.6.0)
- id: `rm-014` | track: reliability | priority: 56.0 | status: candidate
- signals: research.tooling:uv pinned at 0.12.5 cannot emit PEP 751 pylock (0.12.11+ can; 0.12.17 current); osv-scanner CI pin 2.3.8 superseded by v2.6.0 (2026-09-14, publishes SHA256SUMS + SLSA provenance)
- acceptance: Runner uv ≥0.12.11; uv-lockfile-check lane exports and verifies a pylock.toml alongside uv.lock; osv-scanner pinned to 2.6.0 with digest verification from release assets; both lanes green
- evidence: workflow diffs with SHA pins + green lane runs

### Test the genuinely untested agent/ modules (supersedes rm-002's phantom list)
- id: `rm-015` | track: reliability | priority: 84.0 | status: candidate
- signals: assess.no_tests:agent/ — 18 modules verified present without tests (agent/api_error_summary.py, agent/turn_preflight_gate.py, agent/compression_facade.py, agent/transcript_repair.py, ... full list in .conductor/assess/90701c0de…-findings.md) + .github/scripts/run-workspace-checks.mjs; rm-002's list is unsatisfiable (19/21 targets are untracked .worktrees/t_3143b8b5/* paths or '*')
- acceptance: Each of the 18 real agent/ modules + run-workspace-checks.mjs has a test file with ≥1 passing behavior-contract test (no change-detectors); rm-002 retired as superseded once this lands
- evidence: scripts/run_tests.sh tests/agent/ green; file-for-module mapping listed in the PR

### Harden the roadmap sync against dirty scan environments
- id: `rm-016` | track: reliability | priority: 82.0 | status: candidate
- signals: assess.process:ROADMAP.md — rm-002 cites untracked .worktrees/t_3143b8b5/* + literal '*'; rm-001 cites an untracked minified web_dist/react-vendor bundle 4×; rm-003's evidence gate references inference.stale_docs which has no in-repo source; byte-identical ROADMAP landed twice via two channels (commit 3921e8fb86 and origin PR #33)
- acceptance: Sync filters untracked/ignored paths and build output, dedupes signals, cites only in-repo-verifiable evidence, and is idempotent (re-running on a clean checkout produces no duplicate landing); ROADMAP.md regenerated from a clean checkout with rm-002's list corrected
- evidence: re-run of the sync on a clean checkout diffed against the landed file; duplicate-landing check

### Remove the dead _read_env_var and its dead-behavior test
- id: `rm-017` | track: reliability | priority: 66.0 | status: candidate
- signals: assess.dead_code:agent/copilot_acp_client.py:147 — zero production callers (only tests/agent/test_pi_rpc_client.py:464-480) and hardcodes ~/.hermes/.env against the get_hermes_home() convention
- acceptance: Either deleted with its test, or repointed to hermes_constants.get_hermes_home() with a real production caller; no hardcoded ~/.hermes path remains in the module
- evidence: grep _read_env_var (0 hits or 1 production caller); profile-awareness test if kept

### Make Windows venv holder detection token-exact
- id: `rm-018` | track: reliability | priority: 78.0 | status: candidate
- signals: assess.process_identity:hermes_cli/update_cmd_windows.py:178-183 — venv_prefix/root_prefix substring-in-argv fallback classifies any process whose arguments merely mention the path as a holder, feeding taskkill /T /F recovery (:291-341); canonical matcher _hermes_holder_subcommand exists at :228
- acceptance: Holder classification uses full-token/path-exact matching (the canonical matcher pattern); a decoy process with the venv path in its arguments is NOT classified as a holder; windows live lane (wine2e) probe covers the case
- evidence: unit test with decoy argv + wine2e lane run on the branch

### Teach SHA pinning in the plugin-validate action snippet
- id: `rm-019` | track: reliability | priority: 52.0 | status: candidate
- signals: assess.supply_chain:.github/actions/plugin-validate/action.yml:7-8 — usage snippet shows checkout SHA-pinned but the action itself referenced by mutable @main
- acceptance: Snippet shows a SHA-pinned reference (+ # vN comment) for the action; rendered docs regenerated if they embed the snippet
- evidence: grep '@main' .github/actions/plugin-validate/ (0 hits)

### Pin the private-leak sentinel to a digest-verified workflow
- id: `rm-020` | track: reliability | priority: 88.0 | status: candidate
- signals: assess.supply_chain:.github/workflows/private-leak-sentinel.yml:19 — reusable workflow referenced at mutable @main (codeo1io/.github), the only unpinned `uses:` in-tree (30+ siblings are 40-hex SHAs + # vN); runs daily + every PR; HEAD bcf55bbaed is an empty retrigger commit proving out-of-band mutation; gitleaks v8.30.1 publishes gitleaks_8.30.1_checksums.txt (GitHub API verified 2026-09-23)
- acceptance: Sentinel runs either a SHA-pinned reusable workflow ref or a vendored gitleaks install verified against the published checksums before execution; zero mutable action/workflow refs remain under .github/; a planted fake-secret probe proves the scan still detects
- evidence: grep -E 'uses:.*@(main|master|v[0-9]+)$' .github/ shows 0 mutable refs; sentinel lane run showing checksum verification + detection probe

### Run the relay-deadline mirror test on backend-only PRs
- id: `rm-021` | track: reliability | priority: 74.0 | status: candidate
- signals: assess.ci_gap:apps/desktop/src/plugins/hermes-bots/relay-deliver-budget.test.ts:13-16 mirrors tools/bot_relay.py TURN_* constants + hermes_cli/config_defaults.py turn_wait_seconds (the #93911 guard) but ci.yaml:105 gates js-tests on classify 'frontend', set only by apps/ ui-tui/ web/ paths (scripts/ci/classify_changes.py:230-233); the reverse mechanism already exists at classify_changes.py:94-103 (_CROSS_LANGUAGE for desktop-slash-registry.json)
- acceptance: classify_changes.py maps the mirrored backend sources to frontend=true (or the mirror assertions are ported into the Python suite); a backend-only diff touching TURN_ATTEMPT_TIMEOUT_SECONDS runs the JS lane and the mirror test executes; contract proven red on a deliberate mismatch, green on parity
- evidence: classifier mapping unit test + JS-lane (or python-mirror) run on a backend-only diff; ci.yaml unchanged gating

### Port the shell-RPC secret scrub from upstream
- id: `rm-022` | track: reliability | priority: 86.0 | status: candidate
- signals: research.upstream_fix:tui_gateway/methods_tools.py:1466 — the !cmd RPC runs shell=True without build_subprocess_env() child-env sanitization and returns unredacted stdout/stderr (persisted to the transcript); upstream a5c044d2e7 (2026-09-20) applies agent.redact.redact_sensitive_text(force=True, redact_url_credentials=True) before tailing and passes tools.environments.local.build_subprocess_env(); fix absent from this branch AND fork main; sibling path methods_tools.py:497 shares the shape
- acceptance: RPC shell outputs are redacted before return (force + url credentials) and children spawn with sanitized env; regression test in upstream's test_shell_exec_scrubs_child_env_and_force_redacts_rpc_output shape (credential planted in env/output, asserted absent); :497 sibling reviewed in the same pass
- evidence: tests/tui_gateway/ red on base / green after port; upstream a5c044d2e7 as port reference

### Strip secret/consent keys from plugin-pack config seeds
- id: `rm-023` | track: reliability | priority: 62.0 | status: candidate
- signals: research.upstream_fix:hermes_cli/plugin_packs.py — config seeds accept secret/consent keys at any depth; upstream b9dff48435 (2026-09-21, post-v2026.9.21) adds _forbidden_key_reason/_first_forbidden_key/_strip_forbidden_keys (refuse + strip at every depth); absent from this branch AND fork main
- acceptance: Config-seed ingestion refuses or strips forbidden keys at every nesting depth with a named reason; ported tests cover nested and list-contained seeds; legitimate seed keys round-trip unregressed
- evidence: tests/hermes_cli/test_plugin_packs.py ported cases green; upstream b9dff48435 as reference

### Reconcile the branch with fork main before the next implement batch
- id: `rm-024` | track: reliability | priority: 80.0 | status: candidate
- signals: assess.sync:origin/main b4528e6c98 already carries content this branch lacks — the multiplex secrets-scope fix (upstream 4aa9baf139; origin/main gateway/run_adapters.py carries _routed_profile_home ×5, this branch 0); the cycle-1 batch (rm-004/005/007/017/018, held uncommitted) overlaps origin/main #48/#49 landed content; raw SHA gap 5268 behind
- acceptance: Before any new implement batch: content-dedupe (git cherry / symbol grep) every planned unit against origin/main AND upstream; the cycle-1 batch reconciled (drop or rebase units whose content already landed); the multiplex secrets fix verified present or explicitly ported
- evidence: dedupe table (unit → origin/main SHA or 'absent') in the PR notes; grep _routed_profile_home non-zero on the shipping branch

### Digest-gate the JS lane npm installs (perf port)
- id: `rm-025` | track: reliability | priority: 40.0 | status: candidate
- signals: research.upstream_perf:96149253c9 (skip the web build's npm ci when the manifests digest is unchanged) + 8231ea137a (gate the desktop root npm ci on manifests digest + Electron presence) — direct fit for the self-hosted JS lane's node_modules cost
- acceptance: npm ci in the JS lane runs only when the package manifests digest changes (or Electron presence demands it); two consecutive no-change runs skip the install and stay green; digest helper behavior locked by a unit test
- evidence: workflow diff + before/after lane timing cited in the PR; upstream SHAs as reference

### Record adopt/track decisions for the upstream capability stream
- id: `rm-026` | track: customer-experience | priority: 30.0 | status: candidate
- signals: research.upstream_stream:setup-agent catalog search/install (31e59b9441, 5c215ffa21, 829a881a52, #119633/#119644) and gateway.standalone per-profile multiplexer opt-out (0238c9d740, self-framed TEMPORARY shim) — large subsystems landing upstream post-v2026.9.21 while this fork tracks neither
- acceptance: A decision note (adopt now / track / decline, with rationale) recorded for each stream; adopting items mint their own units with acceptance criteria; declining cites the coupling reason (e.g. shim topology)
- evidence: decisions recorded in the ROADMAP cycle log or PR notes; the upstream stream re-checked at the next cycle (no silent drift)

## Cycle log

### Cycle 1 (2026-09-19, conductor run 7f5a1cc7e222) — batch rm-017 + rm-018 + rm-005 + rm-004, stretch rm-007
- status: all five units implemented and locally validated; changes held uncommitted in worktree conductor/run-7f5a1cc7e222 (branch of 3921e8fb86) awaiting the review/shipping stages — no review or shipping outcome is claimed here
- rm-017 → addressed: _read_env_var deleted from agent/copilot_acp_client.py with its dead-behavior test; evidence: grep _read_env_var --include='*.py' → 0 hits; tests/agent/test_pi_rpc_client.py 35 passed (pre-existing timing flake retried once, unrelated surface)
- rm-018 → addressed: holder classification extracted to token-exact predicate _cmdline_indicates_venv_holder (dual-separator path containment; no --python= arm) in hermes_cli/update_cmd_windows.py; decoy-argv contract tests green at tests/scripts/desktop_update/test_venv_holder_token_matching.py; the wine2e live-lane run remains open (CI prohibited this cycle) — recorded as follow-up, unit not fully closed
- rm-005 → addressed: after/before/exclude_session_ids ported by content from upstream 5655920f9a (tool) + 6f793ddbdc (SQL bounds; verified all our routes JOIN sessions) plus the third companion commit's schema-order assertion; evidence: tests/tools/test_session_search.py 59 passed (two clean runs); FTS consumer suites 123 passed
- rm-004 → addressed: 127 upstream-only plugin-catalog YAMLs synced from 1baae3132a (137=137 parity, 9 shared entries format-updated, validator + validator tests synced in lockstep); evidence: python3 scripts/validate_plugin_catalog.py plugin-catalog/ → OK: 137 file(s) valid; catalog loader + loader tests green; loader ignores unknown keys so new upstream fields are safe
- rm-007 → addressed: vision.embed_target_bytes ported by content from upstream f37336522b (8 files incl. tools/vision_tools_history_budget.py); evidence: 43 vision + 125 config tests green
- regression_found_and_fixed (from the full-suite gate): the rm-007 port spawns a single-key vision: config section; CONFIG_SCHEMA auto-derives from DEFAULT_CONFIG, so test_no_single_field_categories failed (orphan 1-field category). Upstream f37336522b carries the latent state and resolves it later by growing the section (max_calls_per_image, abc56351aa). Local fix: _CATEGORY_MERGE["vision"]="agent" in hermes_cli/web_server_config.py — the in-map orphan-fold precedent (runtime #78873); entry carries a drop-when-ported comment. All 6 CONFIG_SCHEMA consumer test files green (99 passed)
- validation: targeted suite 22 files / 352 passed / 0 failed; full suite (sanctioned scripts/run_tests.sh, 4,171 files) 48,133 passed / 31 failed on the immediately-prior tree with the single-file delta closed surgically; every failing file classified pre-existing (plugin cluster, pristine-base A/B) or load/timing flake (8/12 flip green solo; 4 proven on pristine base under identical contention); zero batch-surface failures

### Cycle 1 lessons (prevention rules for future cycles)
- Port upstream features BY CONTENT and expect COMPANION COMMITS: rm-005 needed 5655920f9a + 6f793ddbdc + a third commit's test assertion; rm-007's invariant break was resolved upstream only in a later commit. Before declaring a port complete, diff upstream MAIN's post-feature state of every touched file, not just the feature commit.
- Any port that adds a top-level key to hermes_cli/config_defaults.py must check the web settings-schema category invariant (tests/hermes_cli/test_web_server.py::test_no_single_field_categories): a single-key section spawns an orphan category. Check upstream main's resolution first; the local remedy is the _CATEGORY_MERGE orphan-fold precedent, never deleting the key.
- This environment: full suite ~68-80 min > the 3600s delegate turn — background scripts/run_tests.sh immediately (it survives the turn) and reuse completed runs; never use 'uv run python -m pytest -n 8' (forbidden, #2742). Validation digests must be derived with the FULL 40-char HEAD SHA (short SHA or None yields a wrong trailer and the fold gate rejects it).
- Full-suite failure triage on this box: solo-rerun suspect files first (load flakes flip green), then pristine-base A/B under identical contention for survivors — cron scheduler / gateway drain / compression-sync families are proven tree-independent flakes under 28-worker load.
- Upstream gap analysis must be content-based (git cherry overcounts; vault/honcho exist in-tree despite appearing upstream-only by SHA) — verify every gap claim by content grep before writing a roadmap item against it.

### Cycle 2 candidate seeding (from cycle-1 evidence, pre-review)
- rm-015 (priority 84.0) is the next reliability headliner: 18 genuinely-untested agent/ modules + run-workspace-checks.mjs; pair it with timing-flake hardening of the cron/gateway/compression families proven tree-independent this cycle
- Port upstream abc56351aa (vision.max_calls_per_image) by content, then drop the _CATEGORY_MERGE vision orphan-fold entry added in cycle 1
- rm-012 compression-hardening family and rm-013 SDK majors (anthropic 0.87→1.7, openai 2.24→3.16, mcp 2.0→2.2, agent-client-protocol 0.9→0.12.1) need their own multi-commit cycles; rm-014 CI tooling needs CI lanes this cycle was denied
- rm-016 stays externally blocked (roadmap generator not in-repo); rm-011 stays decision-gated; rm-006/rm-009 are now unblocked sequencing-wise by rm-004's catalog sync landing
- rm-017 is fully closed on deletion; rm-018's wine2e live-lane run and rm-005's E2E date-scoped recall remain as verification follow-ups once CI is available

### Cycle 2 (2026-09-23, conductor run e4f88e0b2434) — batch rm-022 + rm-023 + rm-021, stretch rm-020 (deferred)
- status: all three core units implemented with red-on-base/green proofs, targeted + full-suite validated; changes held uncommitted in worktree conductor/run-e4f88e0b2434 (branch of bcf55bbaed; HEAD bcf55bbaedb07de4471d2d67ed3bec2db2a646b7) awaiting the review/shipping stages — no review or shipping outcome is claimed here
- rm-022 → addressed: the shell.exec RPC (tui_gateway/methods_tools.py:1465) now spawns children under tools.environments.local.build_subprocess_env() — empirical probe: planted OPENROUTER_API_KEY/ANTHROPIC_API_KEY absent from the sanitized child env while PATH survives — and applies agent.redact.redact_sensitive_text(force=True, redact_url_credentials=True) to stdout/stderr BEFORE tailing; the :494-497 quick-command sibling was reviewed and confirmed already hardened in-tree (the reference implementation); new tests/tui_gateway/test_shell_exec_security.py red on base (2 failures with the file stashed) / green after (+13/-2); upstream a5c044d2e7 as port reference
- rm-023 → addressed: the _forbidden_key_reason/_strip_forbidden_keys family ported from upstream b9dff48435 into hermes_cli/plugin_packs.py (refuse + strip secret/consent keys at every nesting depth; our pre-image matched upstream's base exactly, clean content-aligned port; +50/-16); tests/hermes_cli/test_plugin_packs.py 40 green, red-proof exactly the 4 new cases (3 parametrized nested-depth + 1 strip-at-depth) on pre-fix source
- rm-021 → addressed: scripts/ci/classify_changes.py maps the relay-mirror backend sources (tools/bot_relay.py, hermes_cli/config_defaults.py) into the frontend lane via a _FRONTEND_RELEVANT_BACKEND_FILES set — the mirror direction of the existing _PY_RELEVANT_CONTRACT_FILES precedent — so backend-only diffs now run the js-tests gate that carries relay-deliver-budget.test.ts; tests/ci/test_classify_changes.py 75 green, red-proof exactly the 2 new mirror cases; the JS-lane end-to-end proof (vitest executing on a backend-only diff) is deferred per the rm-018 wine2e precedent (CI prohibited this cycle) — recorded as the unit's open verification follow-up
- rm-020 (stretch) → deferred to the first CI-enabled cycle: the mutable @main target lives in the codeo1io/.github repo (out-of-tree); only the caller line .github/workflows/private-leak-sentinel.yml:17-19 is editable in-campaign and the lane-centric acceptance (checksum verification + detection probe) cannot close with local evidence alone
- validation: targeted — scripts/run_tests.sh over the 3 batch test files: 117 passed / 0 failed, ruff clean on all 6 surfaces; full suite (sanctioned scripts/run_tests.sh; the work-order full_command is the forbidden uv/xdist shape) — 4,173 files / 48,775 passed / 27 failed / 383 skipped / 2,312.6s (28 workers), zero batch-attributable regressions: import-graph scan of all 24 failed + 13 flaky files against the changed modules produced zero hits; the lone tests/tui_gateway failure (test_compute_host_turn_protocol.py::test_turn_start_streams_deltas_then_turn_end_with_history_identity) is base-A/B-attributed pre-existing (fails identically on base under dir load; passes solo 4x with the batch); 5 files ran zero tests due to the 300s per-file SIGKILL cap under load (timeout class, not import errors); digest validation:v1:0ae46ccc389335ee6154785a2a64e96437a6b63d178035d2cbb849dec0e60fc3 declared verbatim and re-derived-verified on the unchanged tree

### Cycle 2 lessons (prevention rules for future cycles)
- tui_gateway modules use the bound-globals pattern: the shared namespace (including subprocess) lives on `server` (server.py imports subprocess at :13), so monkeypatch targets in this package must be object-form on `server.subprocess` — mirroring upstream's own patch site; a string-form patch on methods_tools finds no module-level subprocess and stays silently red. Two test iterations were spent learning this; treat it as the default seam for any tui_gateway subprocess test.
- Head-truncated greps nearly minted a false finding (dead-config claim for resolve_embed_target_bytes when the budget IS wired at browser_tool_vision.py:67 / browser_use_cli.py:344 / vision_tools.py:606). Never write a dead-code/zero-consumer claim from a truncated grep — re-run untruncated or with explicit file lists before it enters the ledger.
- classify_changes.py semantics: EVERY `.py` diff also trips the scan lane, so expected-lane sets in classifier tests must include 'scan' for any Python-file case (cost one test iteration; now pinned by the cycle-2 test additions).
- Upstream port discipline that paid off twice this cycle: verify OUR pre-image matches upstream's pre-image before porting (plugin_packs.py matched b9dff48435's base exactly, enabling a clean port; methods_tools.py needed seam adaptation instead). A cheap pre-check that decides port-vs-hand-merge up front.
- Full-suite zero-regression attribution ladder (fastest first): (1) import-graph grep of failed+flaky files against the changed modules — a zero-hit scan closes most cases; (2) solo rerun of survivors (load flakes flip green); (3) base A/B stash for dir-adjacent leftovers. Applied to 37 files this cycle in minutes.
- In run_tests.sh full-suite logs, 'no tests ran' files are usually '(300s exceeded; process tree SIGKILL'd)' timeouts, NOT import errors — read the failure banner class before triage; five whole files (including 261- and 229-test ones) silently lost all coverage to the cap this cycle.

### Cycle 3 candidate seeding (from cycle-2 evidence, pre-review)
- rm-024 (fork-main reconcile gate) remains the mandatory pre-work gate before any cycle-3 implement batch: origin/main carries the multiplex secrets fix (4aa9baf139) this branch lacks; the uncommitted cycle-2 batch (6 surfaces) was verified absent from origin/main this cycle — re-verify with content-dedupe at ship time
- rm-020 (vendored-gitleaks SHA pin / sentinel digest) is the headliner for the first CI-enabled cycle: 5-line caller edit plus out-of-band codeo1io/.github coordination; gitleaks v8.30.1 publishes checksums.txt (verified 2026-09-23)
- New-unit candidates from cycle-2 evidence for the next roadmap phase to mint: (a) test_compute_host_turn_protocol.py parallel-load flake — fails under dir/full-suite load on base AND batch, passes solo 4x; needs event-based sync instead of wall-clock waits; (b) the 300s per-file SIGKILL cap vs slow files — 5 zero-run files this cycle (test_run_agent.py 261 tests, test_hermes_state.py 229, test_local_env_blocklist.py 78, test_execution_flag_detection.py, test_shell_hooks_tree_kill.py); a slow-file lane or cap raise recovers lost coverage
- rm-021's JS-lane end-to-end receipt (vitest green on a backend-only diff) + rm-018's wine2e run are the two queued CI-dependent verification follow-ups; rm-012/rm-013 need dedicated multi-commit cycles; rm-014 needs CI lanes

### Cycle 2 review corrections (independent review 74751bb0, applied additions-only — history above is not edited)
- F1 (HIGH, ledger accuracy) CORRECTION: the cycle-3 seeding claim "the uncommitted cycle-2 batch (6 surfaces) was verified absent from origin/main this cycle" is FALSE for 2 of the 6 surfaces. origin/main b4528e6c98 (fork PR #48, merged via df0e267813, stable since 2026-09-21 — BEFORE this run) already carries upstream a5c044d2e7 verbatim: the done()+build_subprocess_env() hunk at origin/main:tui_gateway/methods_tools.py:1547-1558 (byte-identical to this branch's port) AND upstream's verbatim copy of tests/tui_gateway/test_shell_exec_security.py. rm-023 (_forbidden_key_reason family) and rm-021 (frontend-lane mapping) content remain genuinely absent from origin/main (re-verified by the review with cited greps). Root cause chain: research candidate C1 asserted "fix absent here AND on fork main" WITHOUT a cited fork-main grep (C2/C3 did cite theirs); prioritize repeated it; compound hardened the uncited claim into "verified absent". Consequence for the rm-024 reconcile gate: the SOURCE hunk auto-merges (byte-identical), but the TEST FILE is an add/add conflict — this tree's adapted copy (function-seam _redact_enabled patch, direct _methods dispatch, extra tail-redaction test; required by this tree's redact API) is the copy proven green here (10/10) and is the one to KEEP; upstream's verbatim copy must not silently win the merge.
- F2 (LOW, stat) CORRECTION: the cycle-2 log records methods_tools.py as "(+13/-2)"; the actual numstat is +15/-2 (the implement breadcrumb recorded 15+/2-). Transcription slip, no functional impact. (Related off-artifact slip: the compound phase result understated its insertion as 12 lines/54 total; actual 22 compound lines/64 total content lines — the ROADMAP.md artifact itself was always pure-insertion-verified.)
- AMENDED PREVENTION RULE (extends the cycle-1 "verify every gap claim by content grep" rule): the content-grep bar applies to BOTH remotes — every fork-main (origin/main) absence claim must carry its own cited grep, exactly like upstream claims. An uncited absence assertion may not be hardened into a "verified" claim downstream (prioritize/compound), whatever its source.

<!-- managed by hermes-roadmap render; do not edit by hand -->

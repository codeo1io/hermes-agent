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

<!-- managed by hermes-roadmap render; do not edit by hand -->

## Extension — cycle 2 research (conductor run b45c23b8, 2026-09-22)

> Additions-only append. Upstream gaps verified by content grep in this tree @ bcf55bbaed (upstream/main=439eb0395e, merge-base=345cd2b057; SHA counts overstate — every claim content-checked). The cycle-1 companion-commit rule applies to all ports below.

### Port prompt-caching `cache_ttl: auto` tier selection
- id: `rm-020` | track: customer-experience | priority: 58.0 | status: candidate
- signals: research.upstream_gap:prompt caching — config documents only "5m"|"1h" (hermes_cli/config_defaults.py:640); `effective_cache_ttl()` (agent/prompt_caching.py:114) has no session-pacing input (upstream 23301d705c picks 1h for human-paced / 5m for machine-paced; companions 1ae6f650f9 usage-anchor invalidation, 10659d3536 docs)
- acceptance: `prompt_caching.cache_ttl` accepts `"auto"`; human-paced sessions resolve 1h and machine-paced 5m, pinned by tests; default behavior unchanged; system-prompt byte-stability across turns preserved (caching invariant); companion fix included
- evidence: ported tests/agent/test_prompt_cache_ttl_auto.py green; configuration docs updated

### Detect cross-profile credential collisions at gateway boot and doctor
- id: `rm-021` | track: reliability | priority: 62.0 | status: candidate
- signals: research.upstream_gap:hermes_cli/gateway.py + doctor_state.py carry no collision check (grep collision|shared_channel = 0 hits); CLI-side hermes_cli/profile_channels.py wires only profile_cmd.py:133,169 / profiles.py:841-883 / web_server_messaging.py:287 (upstream 54817f463b adds gateway+doctor detection; ed69aa9e6e is the post-refactor shared-check layout to port)
- acceptance: Two profiles sharing one platform credential are detected at gateway serve time and surfaced by doctor/status with an actionable message; single shared implementation consumed by doctor/status (ed69aa9e6e layout)
- evidence: ported tests/hermes_cli/test_profile_credential_collisions.py green; two-profile repro message cited

### Tolerate a partial fcntl in the WAL lockguard
- id: `rm-022` | track: reliability | priority: 74.0 | status: candidate
- signals: research.upstream_fixes:hermes_state_lockguard.py — no partial/tolerance/disable handling (grep = 0 hits); a partial fcntl currently kills every importer (upstream 524041b9d0, #118269, +34 lines incl. tests/hermes_state/test_lockguard_fcntl_tolerance.py)
- acceptance: A partial fcntl lock disables the WAL guard for that open instead of raising; regression test pins the symptom on base (importer survives a partial fcntl)
- evidence: ported tests/hermes_state/test_lockguard_fcntl_tolerance.py green

### Re-sync the plugin catalog (upstream drift 138 → 239)
- id: `rm-023` | track: customer-experience | priority: 46.0 | status: candidate
- signals: research.upstream_gap:plugin-catalog/ — this tree 138 files vs upstream 239 at 439eb0395e (~101 added since the rm-004 1baae3132a parity: Parallel Search, prompt-enhance 1.0.0, file-tray, vaultknox, gbrain, jev-curator, sabi-metadata, quota v2.4.1, hermes-pubky v0.2.2, aska-digital set, hermes-subscription-meter, protean pair, lancedb-suite v1.5.3, agent-log, browserclaw re-pin 9678a11; Hermes Outpost retired)
- acceptance: Additions-only sync to upstream parity with our divergent entries preserved (rm-004's 137=137 count superseded); validator green on the full set; loader smoke test on one newly added entry
- evidence: python3 scripts/validate_plugin_catalog.py plugin-catalog/ → OK: N file(s) valid (N = upstream count); git diff additions-only

### Port the known-file read/write baseline subsystem
- id: `rm-024` | track: reliability | priority: 44.0 | status: candidate
- signals: research.upstream_gap:tools/file_tools_read_tracking.py + tools/file_tools.py have 0 'baseline' hits; upstream e636aedebf (preserve baselines across partial rereads, +81 lines) and 602e76a88b (bind baseline reads to the task-local path) build on a baseline subsystem this tree lacks
- acceptance: Edit-staleness guards keyed on read baselines that survive partial rereads and bind to task-local paths; scope set after tracing the subsystem's origin commits upstream (verify-first); both fix commits' tests ported green
- evidence: ported tests/tools/test_known_file_write_baseline.py + test_file_read_guards.py green

### Port the scratch-workspace subsystem (24h-idle subtree prune + orphan reap)
- id: `rm-025` | track: customer-experience | priority: 32.0 | status: candidate
- signals: research.upstream_gap:scratch — no scratch subsystem in this tree (0 'scratch' hits in hermes_constants.py; upstream 1217c17f0d prunes on 24h idle judged by the whole subtree, 7fe77f29a7 reaps orphan processes and worktree registrations; touches doctor_state + hermes_constants +51)
- acceptance: Scratch workspaces pruned at 24h idle by whole-subtree mtime with orphan reaping; large port — split into scoped units before implementing; upstream test_scratch_dir.py ported green
- evidence: ported tests/test_scratch_dir.py + orphan-reap regression test green

### Make the code-execution heartbeat a background-only terminal modifier
- id: `rm-026` | track: customer-experience | priority: 26.0 | status: candidate
- signals: research.upstream_gap:tools/code_execution_rpc.py — 0 heartbeat hits in this tree (upstream 9acd0d33b6 blocks the heartbeat in the sandbox; edff33853a diets the schema description)
- acceptance: Heartbeat modifier documented background-only and asserted blocked in the sandbox path; both commits ported (2-line fix class)
- evidence: tests/tools/test_code_execution.py assertion green

### Resolve model-provider plugins per bound profile home
- id: `rm-027` | track: reliability | priority: 40.0 | status: candidate
- signals: research.upstream_gap:providers/__init__.py — no profile-home binding (docstring covers provider-profiles, a different concept); upstream eeb220d40c (#88143, 218-line rework + tests/providers/test_profile_home_layers.py) resolves provider plugins per bound profile
- acceptance: A provider plugin installed under a profile home resolves only for sessions bound to that profile; verify-first that this tree supports profile-homed plugin discovery at all
- evidence: ported tests/providers/test_profile_home_layers.py green

### SHA-pin the private-leak-sentinel workflow and add workflow_dispatch
- id: `rm-028` | track: reliability | priority: 54.0 | status: candidate
- signals: assess.supply_chain:.github/workflows/private-leak-sentinel.yml:18 — sole mutable `uses: …@main` of 39 workflows; no workflow_dispatch trigger (the empty retrigger commit bcf55bbaed exists because of it); violates the repo SHA-pinning policy; rm-019 flagged the class in a docs snippet, this is the live instance
- acceptance: `uses:` pinned to a 40-char SHA with `# vN` comment; workflow_dispatch added; grep '@main' .github/workflows/ → 0 hits; dispatch run exercised once CI lanes are available (ci prohibited this run)
- evidence: workflow diff; grep receipt

### Run the relay budget mirror on Python-only PRs
- id: `rm-029` | track: reliability | priority: 60.0 | status: candidate
- signals: assess.ci_gap:apps/desktop/src/plugins/hermes-bots/relay-deliver-budget.test.ts:13-16 is the sole TS↔PY budget mirror (#93911) but js-tests runs only when frontend=='true' (.github/workflows/ci.yaml:107; scripts/ci/classify_changes.py:230-233); py-only PRs changing tools/bot_relay.py or hermes_cli/config_defaults.py skip it, and the classifier fails open on push — drift lands green-on-PR/red-on-main
- acceptance: classify_changes.py gains a _JS_RELEVANT_CONTRACT_FILES set (mirror of _PY_RELEVANT_CONTRACT_FILES at :98) naming tools/bot_relay.py + hermes_cli/config_defaults.py, forcing frontend=true; a py-only change to those files triggers js-tests on the PR
- evidence: classify_changes unit test + simulated classification output for a py-only diff

### Fix the terminal-backend guidance in tips.md
- id: `rm-030` | track: customer-experience | priority: 30.0 | status: candidate
- signals: assess.doc_drift:website/docs/guides/tips.md:184-189 teaches TERMINAL_ENV/TERMINAL_DOCKER_IMAGE in `.env` — behavioral config in the secrets-only file that hermes_cli/env_loader.py:395-399 actively neutralizes; config.yaml `terminal.backend` is the owner (hermes_cli/config.py:2014-2016)
- acceptance: Section rewritten to config.yaml terminal.backend/docker_image; no `.env` recommendation for non-secret settings remains in tips.md
- evidence: grep TERMINAL_ENV website/docs → 0 .env-recommendation hits

### Split agent/auxiliary_client.py along topic siblings
- id: `rm-031` | track: reliability | priority: 50.0 | status: candidate
- signals: assess.god_file:agent/auxiliary_client.py — 7,630 lines / 376 functions (largest 128), 3.8× the ~2,000-line split signal; file-level instance (rm-001 tracks hot functions only); declared-refactor shape per AGENTS.md
- acceptance: Facade + `auxiliary_<topic>.py` siblings per the Sep-2026 decomposition; no public symbol moves (facade re-exports); tests/agent/ green without test edits beyond import paths
- evidence: per-file line count < 2,000; scripts/run_tests.sh tests/agent/ green

### session_search polish: dead parameter + exclude-cap signal
- id: `rm-032` | track: reliability | priority: 38.0 | status: candidate
- signals: assess.fresh_code_debt:tools/session_search_tool.py:113 `_parse_iso_bound` documents `as_exclusive_end` but never reads it (passed at :589); :160 `_normalize_exclude_session_ids` silently truncates at 20 (`_EXCLUDE_SESSION_IDS_CAP`) so excluded sessions can resurface with no output signal
- acceptance: Dead parameter removed or honored (SQL bounds are already `<`-exclusive); exclude truncation surfaced in tool output when the cap is hit
- evidence: tests/tools/test_session_search.py updated + green

### Verify-then-port note (no id): tui_gateway/prompt_turn.py:75-79 already carries a bounded-recovery comment; before porting upstream a3013c0090 (goal resume after max-iterations, #102213) diff that hunk against this file — presence unverified this cycle.

## Cycle log — cycle 2 (post-Extension append)

### Cycle 2 (2026-09-22, conductor run b45c23b8) — batch rm-022 + rm-021 + rm-029 + rm-028+rm-019 + rm-032, stretch rm-030
- status: all six units + stretch implemented and locally validated; changes held uncommitted in worktree conductor/run-b45c23b895be (branch of bcf55bbaed) alongside the uncommitted cycle-1 batch-branch lineage, awaiting the review/shipping stages — no review or shipping outcome is claimed here
- rm-022 → addressed: hermes_state_lockguard.py partial-fcntl tolerance ported hunk-for-hunk from upstream 524041b9d0 (our module verified byte-identical to upstream's pre-fix shape first): gate os.name=='nt' first, tolerate (ImportError, AttributeError) off-Windows, probe callable(fcntl.fcntl); regression test tests/hermes_state/test_lockguard_fcntl_tolerance.py (95 lines, ported+adapted); red-on-base proven via stash A/B (2 tests fail on the pre-fix module); 7 passed / 1 windows_only skip
- rm-021 → addressed: upstream ed69aa9e6e shared duplicate-credential check ported into hermes_cli/gateway_migrate.py (duplicate_credential_lines reports key NAMES, never values); doctor_state._check_profiles and gateway-status consumers wired; CLI-side profile_channels.py reconciled rather than duplicated; upstream test adapted to our _installed_service seam → tests/hermes_cli/test_profile_credential_collisions.py (67 lines, 2 tests green; neighbors green)
- rm-029 → addressed: _JS_RELEVANT_CONTRACT_FILES inverse seam added to scripts/ci/classify_changes.py so the vitest relay-deliver-budget mirror (reads tools/bot_relay.py + hermes_cli/config_defaults.py) runs the frontend lane on Python-only PRs; tests/ci/test_classify_changes.py 74 passed incl. 2 new contract-lane cases
- rm-028 + rm-019 → addressed: .github/workflows/private-leak-sentinel.yml uses: SHA-pinned to codeo1io/.github@7d47ab484a937c5742ddcb3b69399495e8342beb (ls-remote of refs/heads/main) and workflow_dispatch trigger added (retires the empty-retrigger-commit pattern); .github/actions/plugin-validate/action.yml:8 snippet pinned; tree-wide `uses:.*@main` audit → 0 hits; live-dispatch receipt deferred (CI prohibited this cycle)
- rm-032 → addressed: dead as_exclusive_end kwarg removed from _parse_iso_bound (tools/session_search_tool.py:113; sole other call site passes no kwarg); exclude_session_ids truncation at _EXCLUDE_SESSION_IDS_CAP=20 now surfaced as a response note; tests/tools/test_session_search.py 62 passed incl. 2 new cap-note tests
- rm-030 (stretch) → addressed: website/docs/guides/tips.md:184-189 rewritten from .env TERMINAL_ENV/TERMINAL_DOCKER_IMAGE to config.yaml terminal.backend/terminal.docker_image (matching env_loader.py:395-399 cleanup); same drift class fixed in sibling website/docs/guides/team-telegram-assistant.md
- validation: targeted sweep 10 files → 302 passed / 0 failed / 1 windows_only skip (130.7s); full suite (sanctioned scripts/run_tests.sh) 4,174 files / 48,819 passed / 33 failed / 387 skipped in 2664.9s with ZERO batch-surface failures; zero-regression proven by failure-set attribution: 18 of 33 fail deterministically on the pristine base (batch stashed, 27-file solo rerun), 14 are load flakes (pass solo with batch), 1 is a pre-existing order flake (tests/honcho_plugin/test_pin_peer_name.py fails 2× solo on BOTH base and batch trees) — batch-only failure set EMPTY; validation digest validation:v1:8a179433… re-derived byte-identical to dispatch across both test phases (tree unchanged through validation)

### Cycle 2 lessons (prevention rules for future cycles)
- Port discipline that worked: before porting a fix, byte-compare our module against the upstream PRE-FIX shape (`git show <fix>^:<file>`). Byte-identity (proven for lockguard vs 524041b9d0) means the fix applies hunk-for-hunk and any test adaptation is seam-naming only, never behavior.
- Ported upstream tests reference upstream seam names: our tree had `_installed_service` where upstream's credential-collision test patched a different symbol. Adapt the fixture to OUR seam AND grep the production call site's binding (facade-vs-defining-module, per the repo's patch-where-production-reads rule) before trusting a monkeypatch target.
- Emit incrementally, compile per unit: an implement attempt was interrupted mid-edit leaving a non-compiling tree (missing `Tuple` import + paren imbalance in session_search_tool.py), forcing an honest failed emission and re-dispatch; and a full_tests turn ran a 44-minute suite + A/B and exceeded the 3600s delegate envelope before writing its phase_result. Rules: (a) `python3 -m py_compile` after EACH unit, not at sweep end; (b) write the result-channel JSON the moment mandatory evidence exists — preserved /tmp logs + ndjson breadcrumbs let the re-dispatch reuse the completed suite run without re-running it.
- Full-suite zero-regression accounting (this branch @ bcf55bbaed, 2026-09-22): 33 failures = 18 deterministic pre-existing + 14 load flakes + 1 order flake; deterministic set clusters: dashboard_auth_gate (2), delegation lifecycle (delegate_capacity_interrupt ×3, delegate_timeout_cleanup, zombie_process_cleanup), plugin discovery (test_plugins, plugins_cmd_category_discovery ×2, plugin_scanner_recursion), mcp_serve event-bridge (×2), tui_gateway (×3), plus singles (moa_loop_mode, pi_rpc_client, sequential_tool_interrupt, session_hygiene, update_head_moved_gate, install_macos_launcher, hermes_constants, browser_snapshot_threshold, mcp_capability_gating, mcp_failure_classification, process_registry_list_exit, subprocess_stdin_guard, transcription_tools). Attributed via stash A/B: solo-rerun suspects first, pristine-base rerun for survivors.
- CI classifier lane-gating cuts both ways: fail-open on push + frontend-lane gating meant the vitest↔Python mirror drifted green-on-PR/red-on-main. Whenever a vitest test reads Python sources (or a pytest reads JS manifests), extend BOTH contract-file lists in scripts/ci/classify_changes.py — the rm-029 _JS_RELEVANT_CONTRACT_FILES seam is the template.

### Cycle 3 candidate seeding (from cycle-2 evidence, pre-review)
- The 18 deterministic pre-existing full-suite failures are fresh, evidence-backed reliability targets (none batch-related): dashboard_auth_gate proxy-header pair first (self-contained, hermes_cli), delegation-lifecycle cluster second (suspected shared root cause across 5 tests), then plugin-discovery and mcp_serve event-bridge clusters
- Deferred-by-design this cycle: rm-020 (cache_ttl auto) wants a dedicated caching cycle; rm-015 remains the next headliner per cycle-1 seeding; rm-013/rm-014/rm-018 (wine2e live lane) and rm-028's sentinel workflow_dispatch receipt all require CI lanes
- Unminted verify-first item: prompt_turn.py:75-79 bounded-recovery comment vs upstream a3013c0090 (goal resume after max-iterations) — diff before porting (presence unverified)
- Largest remaining upstream content gaps: rm-023 catalog re-sync (138 vs 239), rm-024 known-file baseline subsystem, rm-025 scratch-workspace subsystem; rm-031 auxiliary_client.py split (7,630 lines / 376 functions / max fn 128) wants its own cycle with the evals/codebase_navigability metrics as before/after evidence

### Cycle 2 erratum (independent-review fix, 2026-09-22 — supersedes the two marked lines above)
- CORRECTED deterministic-18 ledger (re-derived from /tmp/base_ab_868ed09a.log, the pristine-base stash A/B): tests/hermes_cli/test_dashboard_auth_gate.py ×2 (proxy_headers, bounded_trusted_proxy_networks), tests/hermes_cli/test_plugin_scanner_recursion.py::test_depth_cap_two, tests/hermes_cli/test_plugins.py::test_failed_discovery_is_not_cached, tests/hermes_cli/test_plugins_cmd_category_discovery.py ×2 (json_status_uses_key, mixed_flat_and_category), tests/hermes_cli/test_update_head_moved_gate.py, tests/scripts/install/test_install_macos_launcher.py, tests/test_hermes_constants.py, tests/test_mcp_serve.py ×2 (event-bridge poll E2E), tests/tools/test_browser_snapshot_threshold.py, tests/tools/test_delegate.py::test_mixed_composite_is_subtracted_at_child_assembly, tests/tools/test_delegate_timeout_cleanup.py, tests/tools/test_mcp_capability_gating.py, tests/tools/test_mcp_failure_classification.py, tests/tools/test_process_registry_list_exit.py, tests/tools/test_subprocess_stdin_guard.py. The prior enumeration above mislabeled 12 pass-solo LOAD FLAKES as deterministic (delegate_capacity_interrupt ×3, zombie_process_cleanup, tui_gateway ×3, moa_loop_mode, pi_rpc_client, sequential_tool_interrupt, session_hygiene, transcription_tools) and omitted test_delegate mixed_composite + profiles_sidebar_cache/relay_shared_metrics from the accounting; enumerated total 29 ≠ 18. Cycle 3 must seed from THIS ledger, not from the lessons line above; the delegation-lifecycle "cluster" is really 2 deterministic (delegate mixed_composite, delegate_timeout_cleanup) + 3 flakes.
- rm-022 count correction: the log line above says "7 passed"; the file's live result is 4 passed + 1 windows_only skip (3 test functions, one parametrized; re-verified this fix pass). The 7 came from an implement-phase miscount.
- rm-021 acceptance correction: detection surfaces via `gateway status` and `doctor` only — no serve-time check is wired (faithful to upstream 54817f463b + ed69aa9e6e, which also never wired one; hermes_cli/gateway.py:6385 is status-side). A serve-time surfacing unit is a candidate if wanted; until then the acceptance wording "detected at gateway serve time" is wrong.

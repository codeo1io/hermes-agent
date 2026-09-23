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

### Port the fork-main security/maintenance family into this line (two-way reconciliation)
- id: `rm-020` | track: reliability | priority: 88.0 | status: candidate
- signals: assess.divergence:HEAD bcf55bbaed lacks origin/main df0e267813 (six-PR security port) + b4528e6c98 (over-revert restore) — gateway/relay/media.py:68-69,120,124-126 attaches the per-gateway bearer to ANY url containing '/relay/media/' (host-agnostic substring; third-party re-host harvests the credential) and the vulnerable contract is pinned by tests/gateway/relay/test_relay_media.py:239,247; agent/file_safety.py:72-74 single-home guard (TERMINAL_HOME_MODE=profile leaves real-home credential paths unguarded; NT-namespace `\\??\\` guard absent); hermes_state_guard.py lacks import-time real-home capture; agent/pi_rpc_client.py:474 poll() reports clean exits as 'code None'; agent/anthropic_credentials.py lacks OAuth route detection; upstream source for the SSRF family: upstream 3933fdf63b
- acceptance: Each of the five fixes present in this line with its tests (relay tests INVERTED to the hardened contract — third-party host with '/relay/media/' is NOT a re-host); scripts/run_tests.sh tests/gateway/relay/ + file_safety/state_guard/anthropic-credential/pi_rpc suites green; fork-local plugins/model-providers/pi-rpc + opencode-free NOT deleted (upstream deleted them; pi-rpc feeds agent/pi_rpc_client.py + agent/copilot_acp_client.py); the rm-batch features this branch carries (session-search bounds, vision budget, venv-holder predicate) still intact
- evidence: per-fix grep/diff against df0e267813+b4528e6c98; targeted suite outputs; upstream provider-deletion explicitly excluded with cited fork-local consumers

### Re-sync the plugin-catalog delta (+104 entries) and record a sync cadence
- id: `rm-021` | track: reliability | priority: 70.0 | status: candidate
- signals: research.catalog_drift:upstream/main 241 entries vs fork 137 (git ls-tree upstream/main plugin-catalog/ | grep -c yaml → 241) — +104 in ~2 days incl. 4 security-re-pinned entries (openmail→bc8655e a0e252d8f1, localsend 2d95c42aa4, Afterforge baa65cfaf4, filebox→0210dcc8 45d3182cd0); shared-entry audit: 122 identical, 14 metadata-only (zero rev/version/install changes ⇒ no insecure pins carried today); upstream pace is 235 plugin-catalog commits / 12 days ⇒ one-shot syncs (rm-004) go stale in days
- acceptance: catalog at upstream parity (241=241 or documented per-entry exclusions); python3 scripts/validate_plugin_catalog.py → OK; catalog loader tests green; re-pinned entries synced at their HARDENED revisions (never interim pins); cadence rule recorded (e.g. catalog sync runs each cycle or on >N delta)
- evidence: entry-count parity check; validator output; loader suite; diff of the four re-pinned entries showing hardened revs

### SHA-pin the private-leak sentinel reusable-workflow reference
- id: `rm-022` | track: reliability | priority: 58.0 | status: candidate
- signals: assess.supply_chain:.github/workflows/private-leak-sentinel.yml:18 references codeo1io/.github reusable workflow by mutable @main (repo baseline is SHA pins: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2); research.pin_target:codeo1io/.github has NO tags (GitHub REST /tags → []) — commit-SHA pin is the only available form; main = 4e09145d5c8b46620789d21d911bad0878bb06e5 (2026-09-22T13:59:22Z)
- acceptance: sentinel `uses:` references the SHA with a dated `# main@2026-09-22` comment; grep -rn '@main' .github/workflows/ → 0 hits; sentinel lane green once CI is permitted
- evidence: workflow diff + grep receipts; sentinel run output when CI available

### Reconcile roadmap unit statuses with landed cycle-1 work
- id: `rm-023` | track: reliability | priority: 62.0 | status: candidate
- signals: assess.ledger_drift:ROADMAP.md — rm-004/005/007/017/018 (:35,:41,:53,:113,:119) still `status: candidate` while the cycle log (:133-138) records them implemented and the commits landed on this branch (abc427137f, e450795829, 80a9124d1e, 24d3492cdb, 0926c48788); a status-blind queue can re-dispatch landed work
- acceptance: statuses of implemented units advanced out of candidate in the render input (implemented/landed), keeping open follow-ups visible (rm-018 wine2e, rm-005 E2E recall); re-running the ledger read produces no re-dispatch of landed units; append-only history preserved
- evidence: status-vs-cycle-log-vs-landed-commits cross-check output; no unit with a landed commit remains status:candidate

### Minor cleanups on fresh cycle-1 code
- id: `rm-024` | track: reliability | priority: 40.0 | status: candidate
- signals: assess.minor:tools/vision_tools_history_budget.py:21 calls load_config() (deepcopy) per image-embed on the vision/screenshot hot path while load_config_readonly() exists for exactly this; cli-config.yaml.example lacks the new user-facing vision.embed_target_bytes knob (config_defaults.py:1160); cron/scheduler.py:3217 _worker_exited_before_ack(process, returncode) — both params unused (ledger-only classification)
- acceptance: vision embed path reads config via load_config_readonly() (or equivalent no-copy read); cli-config.yaml.example documents vision.embed_target_bytes with a comment; dead parameters removed from _worker_exited_before_ack; targeted suites green (vision, config-template check, cron adopt)
- evidence: hot-path diff + benchmark-free reasoning note; template grep; scripts/run_tests.sh targeted files

### Anchor the sanctioned runner's per-file home pool outside the real Hermes root
- id: `rm-025` | track: reliability | priority: 74.0 | status: candidate
- signals: assess.env_coupling:scripts/run_tests_parallel.py home anchoring — the runner anchors home_root by following TMPDIR, so a harness that parks TMPDIR under the passwd real root (e.g. /home/agent/.hermes/tmp/.../hermes-pytest-home-*) makes the throwaway pool home a state-guard deny-root candidate (conftest's _STATE_DB_GUARD_EXTRA_DENY_ROOTS honors it as a "custom" pre-set home); proven cycle 2: test_live_db_isolation_guard::test_child_without_hermes_home_is_refused, test_log_isolation::test_hermes_home_is_sandboxed_before_imports, and browser_snapshot_threshold::test_cleanup_reloads_updated_profile_config each fail on PRISTINE origin/main under that environment shape
- acceptance: home_root anchored at a short /tmp path (not TMPDIR-following) with throwaway semantics preserved; the three named tests pass under a TMPDIR-under-real-root harness on both this line and pristine origin; no other test's home expectations change
- evidence: probe runs of the three tests under a redirected TMPDIR before/after; full-suite failure-set delta

### Sweep remaining import-time hermes-home pins feeding state handles
- id: `rm-026` | track: reliability | priority: 68.0 | status: candidate
- signals: assess.port_hazard:guard-family ports — tui_gateway/server.py:45 pinned _hermes_home at import and :386 acquired Path(_hermes_home)/state.db until cycle 2's full_tests gate ported origin's #112692 _launch_state_db_path() first-use resolution (7 deterministic suite failures: projects_rpc ×5, resume_live_lazy_session, browser_snapshot_threshold); the same import-time-pin class may persist in siblings (grep module-level get_hermes_home() captures feeding SessionDB/registry acquisitions)
- acceptance: every import-time hermes-home capture whose value feeds a state-handle acquisition is either first-use-resolved (origin #112692 pattern) or proven inert under post-import HERMES_HOME redirection; a grep census lists each site with its disposition
- evidence: grep census + per-site rationale; store-touching suites green under a post-import HERMES_HOME redirect probe

### Harden the cycle-2 flaky-retry files with event-based synchronization
- id: `rm-027` | track: reliability | priority: 46.0 | status: candidate
- signals: reliability.flaky:cycle-2 full suite (delegate spool full_tests/a6a2ca4f…-fullsuite-v5.log) — 13 files failed attempt 1 and passed on retry (⚠ FLAKY class) incl. test_update_wedged_gateway, test_honcho_pin_peer_name, test_isolated_orphan_activity, test_browser_snapshot_threshold, test_local_env_blocklist; the repo flake policy treats pass-on-retry as a bug to fix, not noise
- acceptance: each file either hardened (wall-clock bounds ≥2s, event-based sync, no assert-not races per AGENTS.md flake policy) or root-caused as tree-independent load contention with a recorded rationale; a 28-worker re-run shows no FLAKY lines
- evidence: runner output before/after; per-file hardening notes

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

### Cycle 1 extension (2026-09-23, conductor run f8c01a12 — assess + research phases)
- status: read-only extension — five new units minted (rm-020..rm-024); no prior unit text altered (additions-only append; git diff shows pure insertions)
- assess (attempt a9afba2a): fresh adversarial scan at bcf55bbaed; 7 findings — 2 HIGH (relay-media bearer leak; missing origin/main security port) → rm-020; 1 MEDIUM (sentinel @main) → rm-022; 1 MEDIUM (ledger status drift) → rm-023; 3 LOW (vision hot-path config read, undocumented knob, dead params) → rm-024; cycle-1 batch spot-checks green (4 files / 89 passed)
- research (attempt 11c810d0): upstream divergence 5,719 content-unique commits since ~2026-09-11; catalog +104 delta → rm-021; SDK ladder refined; supply-chain tooling corrections
- refinement to rm-013 (evidence, 2026-09-23 PyPI requires_dist): anthropic 1.8.0 needs httpx2>=2.0.0 — the extra-scoped httpx2==2.7.0 (pyproject.toml:207,279,290) already satisfies, so anthropic is UNBLOCKED; openai 3.18.0 needs httpx2>=2.12.0 — NOT satisfied, so the httpx2 pin must move 2.7.0→>=2.12.0 BEFORE openai 3.x. Ladder: httpx2 bump → anthropic 1.8.0 → openai 3.18.0
- refinement to rm-014 (evidence, 2026-09-23 workflows grep): CI pins uv 0.9.28 at EIGHT sites (docker.yml:151, uv-lockfile-check.yml:77, tests-os.yml:76, lint.yml:47,141,172, e2e-desktop.yml:67, windows-venv-e2e.yml:39) — the unit's '0.12.5' signal understates scope; bump is 8 coordinated pins with lockfile-check parity (uv.lock format moves across minors); latest uv 0.12.17. osv-scanner refresh stays INLINE (google/osv-scanner-action's reusable workflow runs on GitHub-hosted runners — forbidden by org self-hosted-only policy, osv-scanner.yml:50-56); v2.6.0 publishes osv-scanner_SHA256SUMS + SLSA provenance for digest verification
- dismissed with evidence: wholesale upstream rebase/tracking (5,719-commit content drift vs fork-local line — content-port only); planned-stop watcher re-port (gateway/run.py:4362 already carries _run_planned_stop_watcher); adopting upstream provider-set deletions (pi-rpc feeds agent/pi_rpc_client.py + agent/copilot_acp_client.py); separate catalog pin-audit item (verified: none of the 137 carried entries has a superseded security pin — 14 shared diffs are metadata-only); GitHub issues as a user-need channel (disabled on the mirror)
- next-batch seeding suggestion: rm-020 + rm-022 first (security, smallest blast radius), then rm-021 (mechanical, mirrors rm-004's validated process), rm-023 (render-input hygiene), rm-024 last; rm-013/rm-014 remain multi-commit cycles per the cycle-2 seeding above

### Cycle 2 (2026-09-23, conductor run f8c01a12) — batch rm-020 + rm-022 + rm-019 + rm-021, stretch rm-024
- status: all five units implemented and locally validated; changes held uncommitted in worktree run-f8c01a126ed6-f8c01a12 (branch conductor/run-f8c01a126ed6 @ bcf55bbaed, staged +4087/−152 across 154 paths) awaiting the review/shipping stages — no review or shipping outcome is claimed here
- rm-020 → addressed: origin/main df0e267813+b4528e6c98 ported by content — relay-media bearer attach now requires is_own_rehost + SSRF vetting with the vulnerable contract INVERTED (tests/gateway/relay/test_relay_media.py:239,247) and the hardened contract pinned (tests/gateway/relay/test_media_safety.py:61-73); file_safety multi-home + NT-namespace guards; hermes_state_guard real-home capture (byte-identical to origin); pi_rpc bounded reap wait; anthropic OAuth route detection incl. 2b3bab0a5c caller hunks (6 files) + resolve_anthropic_token(model=) wiring. Fork-local pi-rpc/opencode-free providers preserved (upstream deletions excluded); fork vision budget (rm-007) kept fork-side with origin's native_turn_images expectations NOT ported; evidence: anthropic family 541/0 across 56 files, collateral sweeps 349/349, ported relay/file_safety/state_guard suites green
- regression_found_and_fixed (full_tests gate): the state_guard port exposed a fork-line hazard — tui_gateway/server.py:45/:386 pinned the launch home at IMPORT time, so under the sanctioned runner the pool home became a guard deny root and the session-store open was refused (7 deterministic failures: projects_rpc ×5, resume_live_lazy_session, browser_snapshot_threshold). Pristine-origin probe passed 35/35 with 0 guard firings because origin carries #112692 first-use resolution. Fixed in-phase: _HERMES_HOME_AT_IMPORT + _launch_state_db_path() (+16/−6). See rm-026 for the remaining census
- rm-022 → addressed: private-leak-sentinel.yml pins the reusable workflow at codeo1io/.github@4e09145d5c8b46620789d21d911bad0878bb06e5 with a dated comment (codeo1io/.github has no tags — commit SHA is the only pin form); evidence: grep '@main' .github/workflows/ → 0 hits; sentinel lane run deferred (CI prohibited this cycle)
- rm-019 → addressed: .github/actions/plugin-validate/action.yml:8 usage snippet SHA-pinned; evidence: grep '@main' .github/actions/plugin-validate/ → 0 hits
- rm-021 → addressed: catalog at upstream parity 242=242, validator + loader synced in lockstep, and the loader's live-cache staleness API implemented to the contract origin's own desynced tests encode (origin module lags its tests post-restore); evidence: python3 scripts/validate_plugin_catalog.py → OK 242 files; loader suite 84/84. Cadence rule (acceptance leg, recorded durably here): every cycle's research phase re-measures the upstream catalog delta and a sync lands when delta > 0 — upstream pace (~235 catalog commits / 12 days) stales one-shot syncs within days
- rm-024 → addressed: vision embed path reads load_config_readonly() (hot-path deepcopy removed); vision.embed_target_bytes documented in cli-config.yaml.example; dead params removed from _worker_exited_before_ack; evidence: targeted vision/config/cron suites green
- validation: targeted union 30 files → 840 passed / 0 failed / 12 skipped; full suite v4 (implement tree) 48,981/32 fully attributed → in-phase fix → v5 (fixed tree) 49,145 passed / 28 failed / 391 skipped + 13 flaky-passed-on-retry + 3 no-run files closed solo (404/405; sole failure = ledgered pre-existing I58 FTS5); ALL 28 v5 failures attributed — pre-existing both-sides ledger / origin-inherited env-coupled (live_db_isolation_guard, log_isolation, browser_snapshot_threshold: proven failing on pristine origin/main under this harness) / load flakes on batch-untouched files; zero batch-only deterministic failures; emission digest validation:v1:038b08156afcd5ba065a63eb51801432bfe4225e2c4b97a4bd38ce9b0f377925

### Cycle 2 lessons (prevention rules for future cycles)
- Guard-family ports (state_guard real-home capture + conftest passwd basis) REQUIRE a pre-port sweep of import-time hermes-home pins: any module-level get_hermes_home() whose value feeds a state-handle acquisition turns the sanctioned runner's pool home into a deny root and refuses the store open. The upstream companion is #112692 (_launch_state_db_path first-use resolution); porting half of a coordinated upstream change surfaces as deterministic suite failures, not test noise (see rm-026).
- The attribution ladder that closed v3/v4/v5: (1) solo-rerun failed files (load flakes flip green), (2) stash A/B against base (shared = pre-existing; base-only set must be empty), (3) pristine-origin probe via git archive for survivors. Three proven failure classes: pre-existing both-sides; origin-inherited env-coupled (fails on pristine origin under a TMPDIR-under-real-root harness — NOT a batch defect; see rm-025); load flakes on untouched files.
- Origin's own tree can lag itself: the plugin-catalog loader tests encode a live-cache staleness API the origin module lacks (post-restore drift). When a ported test fails against a faithfully ported module, diff origin's module against origin's TESTS first — the tests may encode the intended contract to implement, not current state to copy.
- Turn-budget discipline: the full suite (~40 min) only pays off when backgrounded IMMEDIATELY (detached runs survive the turn); two dispatches were lost to 3600s turn timeouts with the suite complete but the emission not yet written. Prepare artifacts while the suite runs; emit the moment the summary line lands.
- A fix landed mid-validation invalidates earlier suite runs as final proof — rerun the suite (v5) rather than argue attribution, and re-derive the validation digest after ANY executable-surface change (the fold gate re-derives it).

### Cycle 3 candidate seeding (from cycle-2 evidence, pre-review)
- rm-015 (priority 84.0) remains the reliability headliner per the cycle-2 seeding; rm-025 (runner home anchoring) and rm-026 (import-time pin census) are newly minted, directly evidenced by this cycle's regression arc, and cheapest to land immediately after it
- rm-018's wine2e live lane and rm-020/rm-022's workflow lanes need CI once permitted; rm-013's httpx2-first ladder (httpx2 ≥2.12.0 → anthropic 1.8.0 → openai 3.18.0) and rm-014's 8-site uv pin bump (0.9.28 → 0.12.17, lockfile parity) remain multi-commit CI-gated cycles
- rm-021's cadence rule (above) means every future cycle's research phase re-measures the catalog delta — cycle 2 closed +104 entries in ~2 days
- rm-023's scope grew: rm-020/021/022/019/024 are still status:candidate in this ledger while the cycle-2 log above records them implemented-uncommitted — the render must advance all nine drifted units (rm-004/005/007/017/018 + the cycle-2 five) in one pass, keeping open follow-ups (rm-018 wine2e, rm-022 sentinel lane) visible

<!-- managed by hermes-roadmap render; do not edit by hand -->

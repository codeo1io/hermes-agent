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

### Port the upstream SSRF-guard routing for remote-party URL fetches
- id: `rm-020` | track: reliability | priority: 88.0 | status: candidate
- signals: research.upstream_fix:tools/url_safety — upstream 3933fdf63b (2026-09-17) routes provider-response URLs, model-supplied image refs, manifest-derived pet URLs, and remote sitemap <loc> entries through the SSRF guard (raw requests/httpx/urllib today; several bodies cached and deliverable back, so a hostile provider/manifest endpoint can steer server-side fetches at internal/metadata addresses); our tree routes only the gateway platform media paths
- acceptance: Hunk-level content diff of every file 3933fdf63b touches vs this tree; each raw-fetch site present here routes through tools/url_safety (or the ported equivalent); regression tests prove at least the model-supplied-image-ref and sitemap-<loc> sites refuse internal/metadata addresses (red on base, green after)
- evidence: grep for unguarded requests.get/httpx.get/urllib.urlopen on remote-party URL sites → 0 hits; new tests green via scripts/run_tests.sh

### Port the upstream security-fix family (lifecycle guard, api_server sanitize, keychain, oauth)
- id: `rm-021` | track: reliability | priority: 80.0 | status: candidate
- signals: research.upstream_fixes — gateway lifecycle guard recognises Windows command spellings (d966b34cc3); api_server emits the run record's runtime in the canonical _sanitize_runtime_metadata shape (6b5a8fad38 — symbol absent from this tree); Anthropic Keychain mirror through `security -i` with hex payload under its own account + spent-pair-only mirroring (bf5a6f6ae6, 14a3463454 — absent from this tree's hermes_cli/auth.py); Bedrock replays thinking as reasoningText and resends once without redacted blocks on encrypted-content rejection (8437310aed); MCP OAuth login keeps discovered server metadata + token errors carry a redacted body excerpt (f44e73dab6)
- acceptance: Each fix ported by content with a symptom-proving regression test (decoy Windows gateway cmdline NOT lifecycle-killed; runtime metadata shape asserted; keychain mirror round-trip against a stub `security` tool; oauth error text carries a redacted excerpt, never the raw token) and a per-commit port-decision note (ported / already-present / N-A with reason)
- evidence: tests per fix + port notes citing the upstream SHAs; scripts/run_tests.sh on the touched dirs green

### Decide and execute the upstream sync cadence (rolling port-forward)
- id: `rm-022` | track: reliability | priority: 76.0 | status: decision-gated
- signals: research.divergence — last wholesale upstream merge is v2026.9.14 (345cd2b057, 2026-09-14); upstream/main has since accumulated 4,108 commits (4,006 content-new by git cherry) at fleet pace (~650/day) with NO new release tag to anchor on; upstream is actively rewriting the files our local patches diverge in (288 gateway, 152 cron commits in the window)
- acceptance: ADR-style decision recorded (weekly upstream/main merge vs release-tag anchoring vs continued cherry-pick port-forward) with the conflict surface measured (scratch merge or git merge-tree output); first sync executed or a dated execution plan recorded; post-sync `git cherry HEAD upstream/main` count below the agreed threshold
- evidence: the ADR note + scratch-merge conflict list; post-sync git cherry count

### Guard ROADMAP.md against sync-channel truncation (extends rm-016)
- id: `rm-023` | track: reliability | priority: 74.0 | status: candidate
- signals: assess.process — /work/projects/hermes-agent carries an UNCOMMITTED 122-line deletion of ROADMAP.md (fleet-sync renderer output after commit b7483d5a36); committing that working state would erase open items rm-004..rm-019, the cycle log, lessons, and seeding — the renderer cannot reproduce the manual additions-only ledger
- acceptance: The dirty canonical working file restored to committed HEAD state (git checkout -- ROADMAP.md) or consciously superseded by a verified regenerate; the landing pipeline refuses/flags any ROADMAP.md update that deletes non-empty sections present in HEAD (additions-only guard); a dry-run of the sync against committed HEAD shows no truncation
- evidence: git -C /work/projects/hermes-agent status --short ROADMAP.md clean; guard check green on a synthetic truncation attempt
- note: rm-016 covers the generator side; this unit covers the landing/verification side

### Remove the dead as_exclusive_end parameter from _parse_iso_bound
- id: `rm-024` | track: reliability | priority: 40.0 | status: candidate
- signals: assess.dead_api:tools/session_search_tool.py:113 — as_exclusive_end documented in the docstring and passed by the single caller, but never read in the body; exclusivity actually lives in _in_time_window's strict `<` (:157)
- acceptance: Parameter removed with the caller updated (or made load-bearing with a test); the docstring describes the actual date-only→midnight-UTC conversion and states where exclusivity is enforced; session_search + FTS consumer suites green
- evidence: grep as_exclusive_end → 0 hits (or a documented effect + test); scripts/run_tests.sh tests/tools/test_session_search.py green

### Document deliver:api_server in the cron user docs
- id: `rm-025` | track: customer-experience | priority: 30.0 | status: candidate
- signals: assess.docs — the cron deliver target api_server (landed via the fix-apiserver-cron-transcript-reland tag) appears in website/docs only as an HTTP control-plane mention (troubleshooting.md:107); cron.md:18 and guides/automate-with-cron.md do not list it as a delivery target
- acceptance: The cron feature/guide docs list api_server among deliver targets with the transcript-delivery behavior and the no-credential-needed note; docs build green
- evidence: grep -rn api_server website/docs/user-guide/features/cron.md website/docs/guides/automate-with-cron.md → documented entry

### Decide adoption of the upstream gateway feature family
- id: `rm-026` | track: customer-experience | priority: 28.0 | status: decision-gated
- signals: research.upstream_features — RoutingIdentity (frozen identity per inbound event) + route-to-profile by sender user_id; api_server SSE hermes.status events and reasoning streaming on /v1/chat/completions + /v1/responses; opt-in served_model footer; WhatsApp native mentions; opt-in user-channel warning-notification suppression; configurable tts.streaming.min_len first-sentence threshold
- acceptance: Per-feature adopt/skip/defer decision with rationale (fork is reliability-first; each adoption enlarges the upstream conflict surface measured in rm-022); adopted features land with tests and docs
- evidence: decision table recorded in the roadmap/PR; adopted features' tests green

### Triage the pristine-baseline full-suite failure and flake ledger
- id: `rm-027` | track: reliability | priority: 52.0 | status: candidate
- signals: cycle-3 full_tests pristine-base A/B — 16 files / 17 tests fail identically on pristine b7483d5a36 (batch stashed) and on the batch tree: tests/hermes_cli/test_dashboard_auth_gate.py (2), test_plugins_cmd_category_discovery.py (2), test_plugin_scanner_recursion.py, test_plugins.py, test_update_head_moved_gate.py, tests/scripts/install/test_install_macos_launcher.py, tests/test_hermes_constants.py, tests/test_mcp_serve.py (EventBridgePollE2E), tests/tools/test_delegate_timeout_cleanup.py, test_mcp_capability_gating.py, test_mcp_failure_classification.py, test_delegate.py, test_process_registry_list_exit.py, test_subprocess_stdin_guard.py; plus tests/hermes_state/test_hermes_state.py (276 pass / 1 FTS5 failure solo, no-run via per-file timeout under the full suite — the known I58/I59 ledger classes) and 13 flaky-passed-on-retry files (test_profiles_sidebar_cache.py flaked on both trees)
- acceptance: each of the 16 pre-existing failures root-caused (real defect vs env/host mismatch vs timing) and fixed or explicitly accept-and-tracked; hermes_state timeout resolved or reclassified; the flake ledger recorded with solo-vs-load classification per file
- evidence: /tmp/full_tests_6dfc6f91.log (batch tree, 4,173 files / 49,184 passed / 21 failed / 422 skipped) + the base A/B solo run (759 passed / 17 failed across 16 files)

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

### Cycle 2 log (2026-09-19/20 landing window 8deee20d94..1e34831e2779, logged retrospectively by cycle 3's roadmap phase)
- status: all units below landed on main; no review or shipping outcome is claimed here. The cycle-1 log above already covers rm-004/rm-005/rm-007/rm-017/rm-018; this log records the remaining units of the same landing window
- planned-stop / os.kill footgun family: planned_stop_stopper_alive uses the canonical _pid_exists, not raw os.kill (the Windows TerminateProcess footgun class); orphaned via_service planned-stop with a live marker self-cancels; the orphaned marker is cleared via the canonical path helper; self-cancel restarts when the stopper dies mid-drain; via_service contract tests aligned to the shipped orphan-cancel semantics (2 commits)
- delegation/cron: item-57 external-worker adopt failures are logged with a same-tick handoff retry (tests/cron/test_item57_external_worker_adopt.py); R69 start-with-goal on a dead delegate client reopens the session instead of dispatching into the closed client (tag fix-delegate-reopen-dead-client); cron deliver:api_server targets deliver via the session transcript (tag fix-apiserver-cron-transcript-reland)
- parsers: pi tool-marker/result-footer parsers restored after the release repair (production-live via agent/pi_rpc_client.py:40)
- test hygiene: every pytest subprocess isolated from production HOME/HERMES_HOME; pytest temproot anchored at a short path
- coding-context: marker walk-up skips the canonical /tmp even when TMPDIR points elsewhere
- CI: python-tests job 30m→60m, per-file timeout 600s on the 96-core runner, concurrency supersede-and-cancel groups (#22), self-hosted-only runners (#20), Windows footgun encoding sites fixed
- misc: ha_call_service list+comma entity_id normalization restored; contributors fix-driver email mapped
- cycle-3 assess verification: 115/115 green across the 6 fresh/changed suites via scripts/run_tests.sh, including both previously-red files (tests/gateway/test_gateway_shutdown.py, tests/gateway/test_stale_planned_stop_cancel.py — 28/28)

### Cycle 3 candidate seeding (from cycle-3 assess + research, pre-review)
- headliner batch: rm-020 (SSRF-guard port, 88.0) + rm-021 (security-fix family, 80.0) — both are content ports with upstream SHAs, matching the port-by-content lessons below
- rm-023 (74.0) is the quick process fix: restore the canonical ROADMAP.md working state and add the additions-only landing guard; pairs with rm-016 (generator side, still externally blocked)
- trivial batch: rm-024 (dead kwarg) + rm-025 (cron docs) — hours, no risk
- rm-022 (76.0) and rm-026 (28.0) are decision-gated: an operator decision on sync cadence and feature adoption is required before implement can start them
- rm-013 SDK majors evidence refreshed by cycle-3 research (anthropic 1.7.0, openai 3.16.2, mcp 2.2.0, agent-client-protocol 0.12.1 with ACP schema v1.23.0 of 2026-09-18) — still a candidate needing its own multi-commit cycle; the fork-vs-upstream pyproject delta is currently only 12 lines, so no additional dep-port surface exists
- rm-015 (84.0) remains the untested-modules headliner from cycle-2 seeding; rm-012 compression family unchanged
- next free unit ID after this append: rm-027

### Cycle 3 log (2026-09-20, conductor run 17bf3f9a, pre-review)
- status: all 5 selected units (rm-019/020/021/024/025) implemented and validated; changes held UNCOMMITTED in worktree conductor/run-17bf3f9a777f (branch of b7483d5a36) awaiting the review/shipping stages — no review or shipping outcome is claimed here. DO NOT REIMPLEMENT: the full batch diff is present in that worktree (30 tracked files + new tests/tui_gateway/test_methods_images.py; md5 manifest /tmp/pre_stash_md5.txt verified post-restore)
- rm-019 → addressed: .github/actions/plugin-validate/action.yml @main ref pinned to 345cd2b057a452236de401d3534b8502a7465e8d # v2026.9.14 (checkout example pinned too); grep '@main' → 0 hits
- rm-020 → addressed: upstream 3933fdf63b SSRF-guard routing ported by content — all remote-party URL fetches (pet manifest/store, provider_media, image_gen openai plugin, skills_hub sitemap <loc>, tui_gateway methods_images) now route through tools/url_safety.py; upstream's openai-codex hunks N/A (fork has no remote-image fetch surface); 183/183 across the touched suites
- rm-021a → addressed: Windows lifecycle-guard command spellings in cron/lifecycle_guard.py (hermes.exe/.cmd/.bat/.ps1, taskkill, Stop-Process) + ported gateway-restart-loop tests
- rm-021b → N/A: the fork's /v1/runs emits no runtime-metadata twin, so upstream 6b5a8fad38's sanitize fix has no premise here — not ported (porting dead code rejected)
- rm-021c → addressed: MCP OAuth redaction (f44e73dab6) — keep_metadata on HermesTokenStorage.remove, evict+remove(keep_metadata=True) on reauth, redacted bounded token-error excerpt; upstream's OWN test assertion was relaxed by follow-up 2d5d12c33f, and the final contract form was ported, not the interim one
- rm-021d → addressed: Bedrock redacted-content resend-once (8437310aed) in agent/bedrock_adapter.py; 83/83
- rm-021e → addressed: Anthropic Keychain mirror (bf5a6f6ae6+14a3463454) — mirror mechanism ported; the changed region byte-matches upstream 14a3463454; 326 tests green across the credential suites
- rm-024 → addressed: dead as_exclusive_end kwarg removed from tools/session_search_tool.py; exclusive-end semantics re-documented at _in_time_window; 60/60
- rm-025 → addressed: deliver:api_server documented (table row + transcript-delivery section) in website/docs/guides/automate-with-cron.md and website/docs/user-guide/features/cron.md
- validation: targeted 14 covering files 960 passed / 0 failed / 12 host-skips; full suite (sanctioned scripts/run_tests.sh) 4,173 files, 49,184 passed / 21 failed / 422 skipped / 13 flaky-on-retry / 1 no-run; ZERO-REGRESSION proven by pristine-base failure-SET A/B (16/18 failing files reproduce identically on base; the rest are load-timing flakes with zero intersection with the 27 changed surfaces); validation digest validation:v1:1bc33a8b8cd3ee2951446aad2df860198a0353a9f04a47e4867b53bc4f77563e

### Cycle 3 lessons (prevention rules for future cycles)
- Companion-commit lesson REINFORCED (cycle-1 lesson, second instance): upstream fix commits get post-hoc corrections to their OWN tests — f44e73dab6's Bearer-pattern assertion was relaxed by 2d5d12c33f. Always diff upstream MAIN's post-feature state of every touched file and port the final contract form; porting the feature commit verbatim imports a test the upstream itself had to fix.
- Port triage workflow that worked (rm-020/rm-021): blob-compare each candidate file against the upstream commit's PRE-state — identical files take the clean patch (git apply), diverged files get a surgical hand-port; and verify the PREMISE before porting (rm-021b's /v1/runs surface doesn't exist on the fork — the right outcome was N/A, not a dead-code port).
- Harness hazard (conductor): engine-derived validation digests are tree-state-sensitive. The full_tests A/B stash left the worktree pristine across two formatting-only fold-gate turns, so the next dispatch derived a different digest (1bc33a8b…→39c9ee18…) with empty changed_surfaces. RULE: pop any A/B stash BEFORE the turn ends and re-derive the digest at emission time; never end a turn holding a stash that alters executable surfaces.
- Flake-vs-regression triage on this box (second confirmation): full-suite failures are classified by failure-SET A/B against the pristine base under identical contention, plus solo reruns; the 13 flaky-on-retry files and the 3 timing files (session_hygiene fence-cancel, compute_host_turn_protocol, hosted_room_driver_runtime) flip green solo — none are batch regressions. Reuse this recipe; do not chase counts.

### Cycle 4 candidate seeding (from cycle-3 evidence, pre-review)
- rm-027 is the fresh evidence-backed unit: the pristine-baseline failure/flake ledger from cycle-3 full_tests (16 files fail on the UNPATCHED tree — this is fleet-sync debt, not batch debt; hermes_state matches the I58/I59 ledger classes)
- rm-015 (84.0) remains the untested-modules headliner from cycle-2 seeding; rm-012 compression family unchanged; rm-013 SDK majors evidence refreshed by cycle-3 research
- rm-022 (rolling upstream sync, 76.0) and rm-026 (gateway feature adoption, 28.0) stay decision-gated — an operator decision is required before implement can start them; rm-023 (truncation guard) pairs with the additions-only convention this append again followed manually
- cycle-3 implement holds the entire security batch uncommitted: the review/shipping stages carry it from the worktree; next cycle's assessment verifies the landing
- next free unit ID after this append: rm-028

<!-- managed by hermes-roadmap render; do not edit by hand -->

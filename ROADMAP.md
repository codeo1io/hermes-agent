# hermes-agent — Roadmap

> Autonomously maintained by the roadmap sync (reliability-first). Items cite reproducible codebase signals; acceptance is proven by cited evidence.

**Vision**: A reliable, customer-friendly repository advanced by evidence-cited roadmap cycles owned by the autonomy loop

**Pillars**: reliability work outranks customer-experience work; every roadmap item cites reproducible codebase signals; acceptance is proven by cited evidence, never claimed

## Fleet context

- upstreams (this repo builds on): .github, agent
- dependents (changes here affect): (host), agent, dashboard, hermes-infra, hermes-stewardship-dashboard, jarvis, maestro, magic-hermes
- graph: evidence-derived (imports/refs/deploy surfaces); advisory

## Open items

### Add test coverage for 20 untested module(s)
- id: `rm-002` | track: reliability | priority: 100.0 | status: candidate
- signals: reliability.no_tests:.github/scripts/run-workspace-checks.mjs, reliability.no_tests:.worktrees/t_171b1032/.github/scripts/run-workspace-checks.mjs, reliability.no_tests:.worktrees/t_171b1032/acp_adapter/__main__.py, reliability.no_tests:.worktrees/t_171b1032/acp_adapter/auth.py, reliability.no_tests:.worktrees/t_171b1032/acp_adapter/commands.py (+15 more)
- acceptance: Every module in ['.github/scripts/run-workspace-checks.mjs', '.worktrees/t_171b1032/.github/scripts/run-workspace-checks.mjs', '.worktrees/t_171b1032/acp_adapter/__main__.py', '.worktrees/t_171b1032/acp_adapter/auth.py', '.worktrees/t_171b1032/acp_adapter/commands.py', '.worktrees/t_171b1032/acp_adapter/content.py', '.worktrees/t_171b1032/acp_adapter/edit_approval.py', '.worktrees/t_171b1032/acp_adapter/entry.py', '.worktrees/t_171b1032/acp_adapter/events.py', '.worktrees/t_171b1032/acp_adapter/model_catalog.py', '.worktrees/t_171b1032/acp_adapter/permissions.py', '.worktrees/t_171b1032/acp_adapter/provenance.py', '.worktrees/t_171b1032/acp_adapter/server.py', '.worktrees/t_171b1032/acp_adapter/session.py', '.worktrees/t_171b1032/acp_adapter/tools.py', '.worktrees/t_171b1032/agent/account_usage.py', '.worktrees/t_171b1032/agent/acp_openai_bridge.py', '.worktrees/t_171b1032/agent/activity_tracking.py', '.worktrees/t_171b1032/agent/agent_init.py', '.worktrees/t_171b1032/agent/agent_runtime_helpers.py'] has a corresponding test file with at least one passing test
- evidence: full suite green (python -m pytest -q) at HEAD; conductor validation digest validation:v1:<sha> recorded in the shipping PR

### Refactor 20 high-complexity function(s)
- id: `rm-001` | track: reliability | priority: 90.0 | status: candidate
- signals: reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1, reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1, reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1, reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1, reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1 (+15 more)
- acceptance: Each flagged function is decomposed below the branch threshold with behavior locked by characterization tests
- evidence: ast-based branch-count check passes at HEAD (full suite green; conductor validation digest validation:v1:<sha> recorded in the shipping PR)

### Refresh stale top-level documentation
- id: `rm-003` | track: reliability | priority: 43.0 | status: candidate
- signals: reliability.stale_doc:README.md
- acceptance: Docs regenerated/updated; staleness detector reports 0 signals
- evidence: inference.stale_docs returns [] for the repo

### Refresh security-adjacent pins across both ecosystems
- id: `rm-028` | track: reliability | priority: 99.0 | status: candidate
- signals: supplychain.stale_pin:uv.lock:707 (certifi 2026.5.20 vs current 2026.7.22 CA bundle), uv.lock:867 (cryptography 50.0.0 — 50.0.1 fixes CVE-2026-33924 X.509 pileup, 50.0.2 ships OpenSSL 4.0.3), uv.lock:4896 (urllib3 2.7.0 vs 2.8.0), package-lock.json:8097 (brace-expansion 5.0.9 < 5.0.12), package-lock.json:18165 (undici 7.29.0 < 7.29.1), package-lock.json:18816 (vitest 4.1.10 < 4.1.11); issue #129426 (type/security, npm audit report dated 2026-09-30, remediation targets superseded)
- acceptance: uv.lock resolves certifi>=2026.7.22, cryptography 50.0.2, urllib3 2.8.0 (pyproject floors moved per pinning policy); `npm audit --json` reports zero advisories for the #129426 set (brace-expansion>=5.0.12, undici>=6.28.1|7.29.1, vitest>=4.1.11, yaml>=2.8.3); full suite green via scripts/run_tests.sh and desktop/web builds green
- evidence: before/after `npm audit --json`; `git diff uv.lock pyproject.toml package.json package-lock.json`; run_tests.sh summary line; CI lane receipts

### Close the session-store duplication/resurrection class
- id: `rm-029` | track: reliability | priority: 97.0 | status: candidate
- signals: issues #129065 (P1 duplicated history block written to state.db), #129123 (P1 compaction re-sequences a killed turn), #129368 (P2 duplicate assistant rows), #129439 (P2 deleted session resurrected), #129211/#129068 (double render); 16 of 100 open issues carry sweeper:risk-session-state
- acceptance: each P1 reproduced on current main against a real state.db (no mock store) before fixing; invariant tests assert no duplicate (session_id, seq) rows and no resurrection after delete; E2E A→B→A two-home coverage where profile scope is touched; issues closed implemented_on_main with the repro linked
- evidence: repro scripts + invariant tests under tests/hermes_state/; run_tests.sh green; issue threads cite the fixing commit and the red-on-main repro

### Windows update + PM-runtime reliability wave
- id: `rm-030` | track: reliability | priority: 95.0 | status: candidate
- signals: issues #129301 (P1 pm runtime init fails), #129235 (P1 cron worker loses deps silently), #129217 (P2 ASR rule blocks updater), #129238 (P2 WinError 145), #129299 (P2 deep-path failure), #129138 (P2 post-fetch-timeout hang leaves gateway stopped), #129171 (P2 gateway stopped after update), #129136/#129239 (PYTHONPATH generation leak), #129300 (pm gc); label cluster: area/install-update 20 + platform/windows 12 of 100 open issues
- acceptance: every fix lands with a windows-latest lane receipt (wine2e-style live topology for process-topology claims — never posix mocks or patched sys.platform); `hermes update` dry-run and real-run exercised on the runner; PYTHONPATH leakage asserted absent across two successive generations
- evidence: workflow run URLs on windows-12 cores lanes in issue threads; regression tests marked windows_only and listed by scripts/ci/list_os_marked_tests.py; run_tests.sh green on posix lanes

### Harden cron silent-failure modes and the lifecycle-guard regex
- id: `rm-031` | track: reliability | priority: 93.0 | status: candidate
- signals: issues #129281 (P1 catastrophic backtracking in a cron lifecycle regex freezes the dispatcher), #129254 (P1 worker dies silently), #129235 (P1 deps lost silently), #129083 (P2 failed-run archives injected as prior output), #129050 (readiness false negative); comp/cron cluster = 11 open issues
- acceptance: the lifecycle regex rewritten with bounded quantifiers and a red-on-main regression test proving sub-linear match time on the adversarial input; worker death surfaces loudly (errors.log + gateway notification) within one tick; failed-run archives quarantined out of the prior-output path; each former silence broken by a test
- evidence: timing-bound regression test (event-based sync, wall bounds >= 2s per flake policy); run_tests.sh tests/cron/ green; issues closed with receipts

### Move provider SDKs off dead majors (openai 3.x, anthropic 1.x)
- id: `rm-032` | track: reliability | priority: 85.0 | status: candidate
- signals: pyproject.toml:40 openai==2.24.0 as a CORE dep (3.0.0 released 2026-08-12; current 3.22.1 — a full major behind on the always-installed SDK), pyproject.toml:206 anthropic==0.87.0 (pinned in the CVE-2026-34450/34452 response; 1.0.0 2026-08-20 whose breaking change is httpx2 adoption — httpx2 is already a repo dependency); uv.lock:3143, uv.lock:430
- acceptance: openai floor >=3,<4 and anthropic >=1,<2 with pinning-policy bounds and `uv lock` refreshed; call-surface audit of removed/renamed SDK symbols across agent/ providers documented; suite green and provider lanes exercise real request/response shapes for both SDKs
- evidence: pyproject+uv.lock diff; grep audit table of migrated symbols; run_tests.sh full summary; openai 3.0.0 notes pulled from GitHub releases (the CHANGELOG main section for 3.0.0 is empty)

### Track agent-client-protocol 0.12
- id: `rm-033` | track: reliability | priority: 82.0 | status: candidate
- signals: pyproject.toml:310 agent-client-protocol==0.9.0, uv.lock:126; current upstream 0.12.1 — three minors ahead on the ACP standard that drives acp_adapter for VS Code/Zed/JetBrains
- acceptance: pin >=0.12,<0.13; acp_adapter E2E against the real protocol surface (session lifecycle, tool calls, events) rather than mock-transport only; changelog-delta audit 0.10→0.12 documented in the PR
- evidence: uv lock diff; acp_adapter integration receipts; audit notes inline in the shipping PR

### Lock ResponseStore's shared sqlite connection
- id: `rm-034` | track: reliability | priority: 80.0 | status: candidate
- signals: gateway/platforms/api_server.py:718 single sqlite connection opened check_same_thread=False with no Lock, while sibling api_server_run_idempotency.py:110 locks its own; all 14 current call sites sit on the event-loop thread (openai_routes.py:253/272/278/497/510/923/928/938/1116/1120/1133/1145, runs.py:396, api_server.py:4287) but the asyncio.to_thread pattern is used six lines away (api_server.py:644), so cross-thread use is a one-refactor accident
- acceptance: either a threading.Lock mirroring the idempotency store or an explicitly documented event-loop-only invariant plus a guard test; zero behavior delta; suite green
- evidence: patch + tests/gateway test proving serialized multi-statement access; run_tests.sh summary

### Decompose the three god adapters
- id: `rm-035` | track: reliability | priority: 70.0 | status: candidate
- signals: plugins/platforms/discord/adapter.py 7359 lines, telegram 7225, slack 6729 — 3-4x past the ~2000-line split signal, while gateway/platforms core files already follow the sibling pattern; declared mechanical extraction PRs are wanted work per the contribution rubric
- acceptance: mechanical +N/-N extraction per the <stem>_<topic>.py pattern with zero behavior change; static_metrics before/after shows file/function/CC distributions improved; full platform suites green
- evidence: evals/codebase_navigability/static_metrics.py runs (from /tmp cwd) before/after; run_tests.sh platform lanes; diff line counts

### Make open-item signals point at the real tree
- id: `rm-036` | track: reliability | priority: 68.0 | status: candidate
- signals: ROADMAP.md:19-21 rm-002 acceptance enumerates 19 .worktrees/t_171b1032/** paths though `test -d .worktrees` fails (worktree absent; rm-015 already superseded the phantom list); ROADMAP.md:26 rm-001 signals cite hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1, a hash-named bundle absent from the tree (grep = 0 hits); 26 scratch artifacts tracked under .conductor/ (22 of them progress ndjson)
- acceptance: rm-002 signals re-derived from the current tree (fresh detector run or rm-015's real list) or the item closed as superseded-by-rm-015; rm-001 signals repointed at static_metrics output instead of a build artifact; .conductor/ tracking policy decided (gitignore progress/ or archive) and applied
- evidence: delivered 2026-10-01 (implement phase, run 7ebb77fa8176423cbf7e150078b15260): rm-002 marked superseded-by-rm-015 in place; rm-001 signals repointed at static_metrics `cycle1` run of 2026-10-01 (47 files>2k, 7>5k, 3 funcs>300L; cc_max delegate_session 111 / run_tests_parallel main 103 / discord _handle_message 81); `.gitignore` gains `.conductor/progress/`; untracking the 22 already-tracked ndjson (gitignore does not untrack) is queued for the commit gate — `git ls-files .conductor | wc -l` reflects the policy only after that untrack lands

### Route vision inputs natively for local and OpenAI-compatible providers
- id: `rm-037` | track: reliability | priority: 60.0 | status: candidate
- signals: issue #129196 (native multimodal vision routing for local + OpenAI-compatible providers); local-models cluster = 6 open issues
- acceptance: image inputs reach local/OpenAI-compatible providers via their native multimodal endpoints, with the ASCII-conversion fallback used only when a model lacks vision; capability detection table-driven (context-length contract style — no hardcoded model catalogs); tests assert routing relationships, not snapshots
- evidence: provider-lane test receipts; run_tests.sh; issue closed implemented_on_main

### Parity usage/occupancy surfaces and provider-wait logging
- id: `rm-038` | track: reliability | priority: 55.0 | status: candidate
- signals: issues #129236 (usage/context_length occupancy shown in CLI but not desktop), #129228 (provider wait measured but never logged); usage-cost cluster = 5 open issues
- acceptance: desktop usage panel consumes the same occupancy source as the CLI (one store, no forked computation); provider-wait metric emitted to agent.log at INFO on completion; local-only logging — no outbound telemetry without the doctrine's opt-in gate
- evidence: desktop vitest + tui_gateway tests; recorded log-line receipts from a live session

### Desktop Artifacts: hide gone files and add ignore rules
- id: `rm-039` | track: reliability | priority: 50.0 | status: candidate
- signals: issue #129423 (P3; Artifacts pane lists entries whose backing files are gone from disk; no ignore rules)
- acceptance: pane filters entries whose file no longer exists on disk; glob ignore rules persisted beside the owning store; tests cover both behaviors
- evidence: desktop vitest suite green; manual receipt posted to the issue

## Closed items

- `rm-006` Port skills.auto_load from upstream — superseded
- `rm-007` Parameterize the native vision embed budget — superseded
- `rm-008` Refresh video generation model families — superseded
- `rm-009` Auto-install catalog-listed memory providers named in config — superseded
- `rm-010` Add the Blender MCP bridge and backend-local app discovery — superseded
- `rm-011` Decide gateway.multiplex_profiles default (upstream flipped to on) — superseded
- `rm-012` Port the upstream compression/loop hardening family — superseded
- `rm-013` Upgrade provider/protocol SDKs behind provider lanes — superseded
- `rm-014` Refresh CI supply-chain tooling (uv pylock, osv-scanner 2.6.0) — superseded
- `rm-015` Test the genuinely untested agent/ modules (supersedes rm-002's phantom list) — superseded
- `rm-016` Harden the roadmap sync against dirty scan environments — superseded
- `rm-017` Remove the dead _read_env_var and its dead-behavior test — superseded
- `rm-018` Make Windows venv holder detection token-exact — superseded
- `rm-019` Teach SHA pinning in the plugin-validate action snippet — superseded
- `rm-020` Port the upstream SSRF-guard routing for remote-party URL fetches — superseded
- `rm-021` Port the upstream security-fix family (lifecycle guard, api_server sanitize, keychain, oauth) — superseded
- `rm-023` Guard ROADMAP.md against sync-channel truncation (extends rm-016) — superseded
- `rm-024` Remove the dead as_exclusive_end parameter from _parse_iso_bound — superseded
- `rm-025` Document deliver:api_server in the cron user docs — superseded
- `rm-027` Triage the pristine-baseline full-suite failure and flake ledger — superseded

<!-- managed by hermes-roadmap render; do not edit by hand -->

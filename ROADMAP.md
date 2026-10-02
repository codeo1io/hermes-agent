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

### Port the upstream cron routed-fire secret-scope/multiplex family
- id: `rm-077` | track: reliability | priority: 95.0 | status: superseded
- superseded-by: canonical render `rm-040` ("Secret-scope hardening: minimal-env children + the upstream cron routed-fire wave", 2026-10-01) already allocates this exact class; the minimal-env children half shipped here as rm-082. Keeping this open would fork a duplicate open item across the two renders.
- signals: upstream:3833773f7,66e3090a4,65bd3eb33,136135e65,71303c708,e4bb0ed6a,48a49220e,760785dd8,b543b1053,adf3948d7,81765d355,9c5da5a1c (2026-09-30); absence:source_supplied_names,absence:_install_fire_secret_scope (git grep empty at c4da06121c); class: unbound profile-scope reads named in root AGENTS.md
- acceptance: `git grep -l source_supplied_names` and `git grep -l _install_fire_secret_scope` return hits in cron/; routed cron fires run under multiplex semantics at the worker handoff with launch-profile dotenv residue stripped and the managed .env composed into every profile secret scope; removed secret sources are revoked from os.environ; a two-home A→B→A multiplex E2E proves a routed fire sees only the routed profile's secrets
- evidence: ported upstream tests (27bbbda5c, 3b3b61ff4 invariants) plus the new two-home E2E green via scripts/run_tests.sh; conductor validation digest validation:v1:<sha> recorded in the shipping PR

### Port the upstream gateway-restart successor-incarnation credit family
- id: `rm-078` | track: reliability | priority: 88.0 | status: done
- done-receipt: hand-ported the upstream final semantics (d5c809790..57a22675e review rounds: successor dicts, unambiguous-baseline guard, missing-evidence logging) into hermes_cli/update_inventory.py + hermes_cli/update_cmd_fleet.py; tests/hermes_cli/test_restart_plan_reconciliation.py 30 passed / 0 failed via scripts/run_tests.sh, incl. the external-install regression (proven red by mutation: disabling the row_is_external filter fails exactly 1 test); `git grep -nE '"(serve|gateway)" *in ' hermes_cli/ gateway/` shows no new substring identity checks (2 pre-existing ban-documenting docstrings in unchanged files); upstream kwargs failed_respawn_pids/external_gateway_pids deliberately NOT ported (our older match_runtime_outcomes lacks them); full CI green on ephemeral PR #108 (12 pass / 0 fail jobs). Canonical render `rm-055` tracks the broader successor-crediting port family.
- signals: upstream:d5c809790,f42fd748c,2594c5786,b7bb7685d,57a22675e (2026-09-30); absence:incarnation-credit in hermes_cli/update*.py, gateway/status.py; class: process-identity confusion (~10 fleet-update issues per root AGENTS.md)
- acceptance: gateway restarts are credited by successor incarnation, not service name; successor-credited restarts require an unambiguous baseline; missing successor evidence for a planned gateway is logged; no new argv/service-name substring matching is introduced
- evidence: scripts/run_tests.sh tests/hermes_cli/test_restart_plan_reconciliation.py -> 30 passed / 0 failed; CI run on ephemeral PR #108 conclusion SUCCESS; review artifact delegate/21a1232bcf9949dc8e51c4b12b6b5640.json verified port fidelity (_live_gateway_pids_from_fleet byte-identical to 57a22675e pre-external-filter)

### Catch the release line up to upstream v2026.9.24 (v0.21.5)
- id: `rm-079` | track: reliability | priority: 82.0 | status: candidate
- signals: release:v2026.9.24 published 2026-09-24 (GitHub releases API) vs fork `git describe --tags --abbrev=0` -> v2026.9.21; upstream compare 345cd2b057...main ahead_by=11716 (agent/ = 216 of 300 sampled files)
- acceptance: fork HEAD contains the v2026.9.24 release-line deltas for the families the fork tracks (cron, gateway, desktop, secrets), either by rebasing the port set onto the release line or cherry-picking its deltas with conductor-landing commit shape preserved
- evidence: `git describe --tags` reports v2026.9.24 or the release tag commit is an ancestor of HEAD; full suite green; diff review shows no over-reverts (per AGENTS.md squash-merge guard)

### Filter phantom signals out of the roadmap sync
- id: `rm-080` | track: reliability | priority: 78.0 | status: superseded
- superseded-by: canonical render `rm-052` ("Roadmap signal scanner must cite only tracked files") + `rm-068` ("Re-baseline phantom roadmap signals rm-001/rm-002 from the tracked tree", 2026-10-01) allocate exactly this class — the dirty-scan recurrence at b8a6730407 IS this item's evidence. Keeping this open would fork a duplicate open item across the two renders.
- signals: rm-002 signals cite .worktrees/t_171b1032/** paths (stale scratch worktree counted as 20 'untested modules'; upstream rm-015 called this list phantom); rm-001 signals cite hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1 (minified vendored bundle) as a complexity hot function
- acceptance: the roadmap sync ignores .worktrees/**, hermes_cli/web_dist/**, and other vendored/minified assets when deriving signals; regenerated ROADMAP.md carries no signal under those prefixes; a unit test pins the ignore filter
- evidence: regenerated ROADMAP.md diff shows the phantom signal lists gone; filter unit test green; full suite green

### Open a provider-SDK major-bump lane (openai 3.x, anthropic 1.x)
- id: `rm-081` | track: reliability | priority: 72.0 | status: superseded
- superseded-by: canonical render `rm-047` ("Provider/protocol SDK major refresh (P2, successor to rm-013; respects the rm-034 Python-3.14 lane)", 2026-10-01) allocates this exact class for both fork and upstream pins. Keeping this open would fork a duplicate open item across the two renders.
- signals: pin:pyproject.toml:40 openai==2.24.0 vs PyPI 3.22.1; pin:pyproject.toml:206 anthropic==0.87.0 vs PyPI 1.9.0 (pin already carries CVE-2026-34450/34452 comments); currency: mcp==2.2.0, pydantic==2.13.5, discord.py 2.7.1 are latest (drift is provider-SDK-specific)
- acceptance: openai and anthropic pins move to (or past) 3.x / 1.x with a fresh CVE-note comment; `uv lock` regenerated; evals/ provider lanes and the model-catalog regression suite green; no behavioral change in provider selection order
- evidence: pyproject diff + uv.lock diff in the shipping PR; evals/ provider lanes green; full suite green

### Build a minimal child-env helper for plugin child processes
- id: `rm-082` | track: security | priority: 68.0 | status: done
- done-receipt: plugins/child_spawn_env.py `minimal_child_env` allowlist helper shipped and used at all three sites (photon adapter sidecar, buzz adapter CLI, openviking __init__ server); grep shows no remaining `os.environ.copy()` at those sites (documented PYTHONPATH strip preserved); planted-Tier-1-secret invariants + Windows-arm + egress-proxy-routing passthrough tests = tests/plugins/test_child_spawn_env.py 5 passed / 0 failed via scripts/run_tests.sh; per-site env tests green (test_sidecar_env, test_cli_env, test_openviking_server_env); targeted battery over the batch's 18 impacted files = 504 passed / 0 failed; full CI green on ephemeral PR #108 (12 pass / 0 fail jobs). Canonical render `rm-040` bundles this class with the cron routed-fire wave (superseded here as rm-077).
- signals: env-copy:plugins/platforms/photon/adapter.py:922 (long-lived detached node sidecar), plugins/platforms/buzz/adapter.py:395 (per-invocation CLI child), plugins/memory/openviking/__init__.py:981 (strips only PYTHONPATH); posture: agent/proxy_sources/iron_proxy.py:740 and agent/transports/codex_app_server.py:100 document the minimal-env requirement
- acceptance: one shared allowlist-based env builder is used at all three sites (documented PYTHONPATH strip preserved); an invariant test asserts a spawned child's environment contains no operator Tier-1 secrets beyond the vars the child needs
- evidence: scripts/run_tests.sh tests/plugins/test_child_spawn_env.py -> 5 passed / 0 failed; `grep -n 'os.environ.copy()' plugins/platforms/photon/adapter.py plugins/platforms/buzz/adapter.py plugins/memory/openviking/__init__.py` -> empty; CI run on ephemeral PR #108 conclusion SUCCESS

### Eliminate source-reading tests
- id: `rm-083` | track: test-quality | priority: 62.0 | status: done
- done-receipt: all 6 sanctioned files rewritten to behavior contracts (test_callable_api_key, test_trajectory_compressor_async, test_session_db_private_access, test_browser_content_none_guard, test_setup_matrix_e2ee [compat-pointer guard correctly deleted], test_openviking_provider); `git grep -nE "(read_text|open)\([^)]*['\"][^'\"]*\.py['\"]" -- tests/` returns only the pre-existing argv-data false positive tests/scripts/desktop_update/test_venv_holder_token_matching.py:43 (file unchanged by the batch); rewritten tests proven red on deliberately broken implementations (browser None-guard mutation -> 4 failed); targeted battery 504 passed / 0 failed; full CI green on ephemeral PR #108. Second-generation source-readers (inspect.getsource class) tracked as rm-087; canonical render `rm-035` tracks its own 4-file set (test_kanban_wave12_ghost_dispatch, test_update_fleet_check_fail_closed, test_update_fetch_failure_classifier, test_single_query_clarify).
- signals: source-read:tests/agent/test_callable_api_key.py:224, tests/test_trajectory_compressor_async.py:87-93, tests/acp_adapter/test_session_db_private_access.py:87+110, tests/tools/test_browser_content_none_guard.py:55, tests/hermes_cli/test_setup_matrix_e2ee.py:8; policy: root AGENTS.md bans reading source in tests outright
- acceptance: zero tests under tests/ open or read_text a `.py` source file; each rewritten test asserts the same behavior contract through a pure/DI-testable function (e.g. the Entra callable-api-key routing predicate); regression intent preserved
- evidence: scripts/run_tests.sh over the 6 rewritten files -> green (504-test targeted battery); proven-red mutation checks recorded in delegate/21a1232bcf9949dc8e51c4b12b6b5640.json evidence; CI run on ephemeral PR #108 conclusion SUCCESS

### Join the upstream godfile-eradication effort
- id: `rm-084` | track: maintainability | priority: 55.0 | status: candidate
- dedup-note: splits of auxiliary_client.py and the upstream-extraction ports are allocated in the canonical render as `rm-057` / `rm-032` (and desktop main.ts as `rm-064`); this item keeps only the scope none of those name — the 22.9k-line tests/tui_gateway/test_tui_gateway_server.py and the 7k-line platform adapters — coordinating with, not duplicating, those.
- signals: upstream-issue:#78647 (82 comments, top open issue; residual ~2K tasks after #102117); size:agent/auxiliary_client.py=8193 lines (8 siblings already exist), platform adapters 7359/7225/6729, tests/tui_gateway/test_tui_gateway_server.py=22910; policy: root AGENTS.md ~2,000-line split signal
- acceptance: at least the top fork offenders (auxiliary_client.py, the 22.9k-line tui_gateway test module) are split along topic/methods_*.py seams with characterization tests locking behavior; evals/codebase_navigability/static_metrics.py before/after recorded in the PR; coordination note with upstream #78647 to avoid port conflicts
- evidence: static_metrics output shows file-size distribution shift; full suite green; no behavior change beyond moves (diff is mechanical)

### Cross-gateway bot collaboration (capability spike)
- id: `rm-085` | track: capability | priority: 40.0 | status: candidate
- signals: upstream-issue:#97681 (30 comments, 2nd top open issue — 'Let Bots collaborate across gateways'); substrate in-tree: gateway/relay/, gateway/platforms/api_server.py, gateway/host_attach.py, host_rendezvous.py
- acceptance: a spike lets two gateway instances exchange a supervised bot handoff via the existing relay/api_server substrate with token-auth; footprint stays at rung 1-2 (extend relay + a CLI command/skill), `_HERMES_CORE_TOOLS` in toolsets.py is unchanged
- evidence: A↔B E2E against two temp HERMES_HOME gateways; toolsets.py diff empty; docs page added under website/docs/developer-guide/

### Watch the upstream plugin lifecycle-event catalog / hook taxonomy
- id: `rm-086` | track: architecture | priority: 25.0 | status: candidate
- signals: upstream-issue:#64231 (28 comments — 'lifecycle-event catalog, hook taxonomy, batch disposition'); policy: root AGENTS.md forbids speculative hooks with no concrete consumer
- acceptance: no divergent local hook surface is introduced; when upstream lands the catalog, a decision note records adopt/port/skip with the compat-window consequences; until then this item only tracks
- evidence: decision note committed under .conductor/ or website/docs/developer-guide/plugins/ at adoption time; plugins/ diff empty in the interim

### Convert the second generation of source-reading tests (inspect.getsource class)
- id: `rm-087` | track: test-quality | priority: 58.0 | status: candidate
- signals: source-read (inspect.getsource/read-text class, derived at c4da06121c after rm-083's six rewrites): tests/hermes_cli/test_kanban_wave12_ghost_dispatch.py:109, tests/hermes_cli/test_update_fleet_check_fail_closed.py:147+158, tests/hermes_cli/test_update_fetch_failure_classifier.py:111, tests/hermes_cli/test_single_query_clarify.py:68+72, tests/hermes_cli/test_update_self_lock.py:247-263, tests/hermes_cli/test_cli_goal_interrupt.py:146, tests/hermes_cli/test_cli_quiet_stdout_leak.py:36-39, tests/test_budget_source.py:35+46; policy: root AGENTS.md bans reading source in tests outright
- acceptance: each listed test asserts its contract through behavior (call the code / a DI-testable extraction) instead of regexing module source; `grep -rn 'inspect.getsource' tests/` returns only sites that exercise the mechanism under test, not product-source assertions; proven-red mutation check for each rewritten guard
- evidence: scripts/run_tests.sh over each rewritten file green; canonical render `rm-035` tracks a 4-file subset of this same class — coordinate ids, don't duplicate closed work

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

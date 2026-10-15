# hermes-agent — Roadmap

> Autonomously maintained by the roadmap sync (reliability-first). Items cite reproducible codebase signals; acceptance is proven by cited evidence.

**Vision**: A reliable, customer-friendly repository advanced by evidence-cited roadmap cycles owned by the autonomy loop

**Pillars**: reliability work outranks customer-experience work; every roadmap item cites reproducible codebase signals; acceptance is proven by cited evidence, never claimed

## Fleet context

- upstreams (this repo builds on): none
- graph: evidence-derived (imports/refs/deploy surfaces); advisory

## Open items

### Add test coverage for 10 untested module(s)
- id: `rm-002` | track: reliability | priority: 100.0 | status: candidate
- signals: reliability.no_tests:.github/scripts/run-workspace-checks.mjs, reliability.no_tests:agent/api_request_hooks.py, reliability.no_tests:agent/auxiliary_health.py, reliability.no_tests:agent/chat_completion_stream_monitor.py, reliability.no_tests:agent/credential_pool_admin.py (+5 more)
- acceptance: Every module in ['.github/scripts/run-workspace-checks.mjs', 'agent/api_request_hooks.py', 'agent/auxiliary_health.py', 'agent/chat_completion_stream_monitor.py', 'agent/credential_pool_admin.py', 'agent/lazy_forward.py', 'agent/transcript_repair.py', 'agent/turn_preflight_gate.py', 'agent/turn_response_intake.py', 'agent/turn_stop_gates.py'] has a corresponding test file with at least one passing test
- evidence: pending — full suite green (python -m pytest -q) at HEAD; conductor validation digest recorded in the shipping PR on acceptance

### Refactor 20 high-complexity function(s)
- id: `rm-001` | track: reliability | priority: 90.0 | status: candidate
- signals: reliability.complexity_hot:agent/agent_runtime_helpers.py::anthropic_prompt_cache_policy, reliability.complexity_hot:agent/auxiliary_client.py::_resolve_task_provider_model, reliability.complexity_hot:agent/model_metadata.py::get_model_context_length, reliability.complexity_hot:agent/turn_usage.py::record_response_usage, reliability.complexity_hot:evals/desktop_bug_campaign/persistence_live.py::main (+15 more)
- acceptance: Each flagged function is decomposed below the branch threshold with behavior locked by characterization tests
- evidence: pending — ast-based branch-count check passes at HEAD (full suite green; conductor validation digest recorded in the shipping PR on acceptance)

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

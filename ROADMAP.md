# hermes-agent — Roadmap

> Autonomously maintained by the roadmap sync (reliability-first). Items cite reproducible codebase signals; acceptance is proven by cited evidence.

**Vision**: A reliable, customer-friendly repository advanced by evidence-cited roadmap cycles owned by the autonomy loop

**Pillars**: reliability work outranks customer-experience work; every roadmap item cites reproducible codebase signals; acceptance is proven by cited evidence, never claimed

## Fleet context

- upstreams (this repo builds on): .github, agent
- graph: evidence-derived (imports/refs/deploy surfaces); advisory

## Open items

### Reassess test coverage using tracked source paths
- id: `rm-002` | track: reliability | priority: 100.0 | status: candidate
- signals: reliability.no_tests:.github/scripts/run-workspace-checks.mjs
- acceptance: Recompute the untested-module cohort from git-tracked source on a clean checkout, excluding ignored worktrees and generated outputs; verify each candidate genuinely lacks coverage before adding tests. Never count scratch copies as independent untested modules.
- evidence: clean tracked-source inventory, reproducible test mapping and targeted test output

### Restore main's required CI checks to green
- id: `rm-078` | track: reliability | priority: 100.0 | status: candidate
- acceptance: (1) exactly one ruff config authority survives (ruff.toml XOR pyproject [tool.ruff]) and lint.yml's comment names the real one; (2) ruff check . and scripts/check-windows-footguns.py --all report zero findings on a clean checkout of main; (3) python scripts/check passes on clean main; (4) code-health ratchet covers the delegation stack (tools/delegate_session_tool.py, agent/opencode_client.py, agent/pi_rpc_client.py) so autonomy checkpoints cannot land red; (5) a push run on the landing commit shows both blocking lint lanes and the aggregate gate green
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Adopt upstream v0.22.2 (never v0.22.1)
- id: `rm-079` | track: reliability | priority: 98.0 | status: candidate
- acceptance: (1) v0.22.2 tag merged (never v0.22.1); (2) every collision has a documented resolution before merge: sessions.auto_prune default-on (90-day startup deletion) vs fork housekeeping/vacuum gates; session_reset idle/daily retirement; tool renames (todo->todo_list, cronjob->cronjob_manage, process->process_manage); plugin compat import layer removal; one-gateway-per-machine multiplex vs HX002 profile-binding seams; pm-owned envs; Python 3.14 runtime (KittenTTS unavailable); (3) fork features rebased and green: turn-lease focused battery + delegation-stack tests; (4) full_tests differential under the sanctioned CI A/B shape (patch-identical mirror PRs, census union; the v0.21.7 baseline of ~534 CI failures must not grow on the fork-delta leg)
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Clear the two JS-lane blockers
- id: `rm-080` | track: reliability | priority: 95.0 | status: candidate
- acceptance: (1) the engines contract is re-pointed at pm's node provisioning (or install.sh regains gates for every engines arm) and tests-js/engines-satisfiable.test.ts passes from a clean checkout without network; (2) the JS & TS lane installs libx11-dev/libxi-dev (or otherwise compiles/skips the x11 monitor) and is green on a main push run
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Refactor verified tracked complexity hotspots
- id: `rm-001` | track: reliability | priority: 90.0 | status: candidate
- signals: reliability.complexity_hot:agent/auxiliary_client.py::L1
- acceptance: Recompute branch complexity from tracked source files only, exclude ignored web_dist bundles, then characterize and refactor a verified hotspot without changing behavior.
- evidence: clean tracked-source complexity report, characterization tests and focused validation

### Guard the roadmap render to tracked signals
- id: `rm-081` | track: reliability | priority: 90.0 | status: candidate
- acceptance: (1) an in-repo guard test parses ROADMAP.md and fails when any signals/acceptance-cited path is untracked or nonexistent (proven red on the pre-fix render, green after); (2) ROADMAP carries tracked-only signals from here on; renderer-side ignore-respecting scan filed to the autonomy stack
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Forward-port gateway host-lock identity if adoption slips
- id: `rm-082` | track: reliability | priority: 88.0 | status: candidate
- acceptance: (1) liveness never infers identity from argv substrings; host-lock/boot-epoch decide; (2) invariant tests are red on base for the recycled-PID and post-reboot-refusal cases and green after; (3) gateway/AGENTS.md HX003 guidance is updated to the new doctrine
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Add real coverage for genuinely untested tracked modules
- id: `rm-083` | track: reliability | priority: 85.0 | status: candidate
- acceptance: a fresh tracked-tree scan produces the cohort of modules with no corresponding test file (listed in the PR); every cohort module gains a test file with at least one passing test run via scripts/run_tests.sh; suite delta green
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Decompose tracked complexity hots
- id: `rm-084` | track: reliability | priority: 80.0 | status: candidate
- acceptance: flagged functions decompose below the branch threshold with characterization tests locking behavior; auxiliary_client.py shrinks or carries an explicit per-unit offset plan under the code-health ratchet rules
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Move fork updates to upstream release channels
- id: `rm-085` | track: reliability | priority: 70.0 | status: candidate
- acceptance: fork update docs describe channel selection and rollback; an update dry-run follows the release tag without a stitch commit
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Post-adoption capability shortlist
- id: `rm-086` | track: reliability | priority: 60.0 | status: candidate
- acceptance: acp_adapter ImportErrors eliminated from the full-suite census; each capability decision recorded with its upstream issue ref and a fork-fit note
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Two low-severity cleanups
- id: `rm-087` | track: reliability | priority: 40.0 | status: candidate
- acceptance: the fallback names an uploadable artifact (or the handoff JSON provably exists at the tag path); the next AGENTS.md addition routes to an area file and the hub stays under cap
- evidence: campaign-recorded in hermes-agent ROADMAP.md

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

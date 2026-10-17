# hermes-agent — Roadmap

> Autonomously maintained by the roadmap sync (reliability-first). Items cite reproducible codebase signals; acceptance is proven by cited evidence.

**Vision**: A reliable, customer-friendly repository advanced by evidence-cited roadmap cycles owned by the autonomy loop

**Pillars**: reliability work outranks customer-experience work; every roadmap item cites reproducible codebase signals; acceptance is proven by cited evidence, never claimed

## Fleet context

- upstreams (this repo builds on): .github, agent
- graph: evidence-derived (imports/refs/deploy surfaces); advisory

## Open items

### Restore main's required CI checks to green
- id: `rm-078` | track: reliability | priority: 100.0 | status: candidate
- signals: assess 2026-10-17 N1/N2/N3/N4: gh run 38951784747 on 682c8a41a9d has 7 failed lanes incl. ruff enforcement (blocking) + Windows footguns (blocking) + 'All required checks pass (v2)'; main push runs red since 2026-10-08T20:15Z (37838062378); pinned-tool repro: ruff check . -> 134 errors (UP006 x52, RUF100 x16, UP037 x16, PLR0402 x13; tools/delegate_session_tool.py 26, agent/opencode_client.py 23, agent/pi_rpc_client.py 16), scripts/check-windows-footguns.py --all -> 7 findings; tracked ruff.toml shadows pyproject [tool.ruff] (ruff --show-settings proves preview=disabled, pyproject inert); offenders are fork-only (404 upstream @v0.22.2) and upstream main is CI-green under a byte-identical ruff.toml
- acceptance: (1) exactly one ruff config authority survives (ruff.toml XOR pyproject [tool.ruff]) and lint.yml's comment names the real one; (2) ruff check . and scripts/check-windows-footguns.py --all report zero findings on a clean checkout of main; (3) python scripts/check passes on clean main; (4) code-health ratchet covers the delegation stack (tools/delegate_session_tool.py, agent/opencode_client.py, agent/pi_rpc_client.py) so autonomy checkpoints cannot land red; (5) a push run on the landing commit shows both blocking lint lanes and the aggregate gate green
- evidence: pinned-tool outputs at the bumped pin (ruff 0.15.10 -> 0.17.1, baseline re-run in the same change), gh run view <landing> --json jobs, ratchet config diff

### Adopt upstream v0.22.2 (never v0.22.1)
- id: `rm-079` | track: adoption | priority: 98.0 | status: candidate
- signals: research 2026-10-17 R1/R2/R3: upstream shipped v0.22.0/v0.22.1/v0.22.2 past our v0.21.7 base; v0.22.1 was built from the wrong commit (Store 'Connecting' stick) and v0.22.2's known issue is that sessions created under the 0.22.1 gateway can't be deleted; compare v0.21.7...v0.22.2 = 2,983 commits while fork-patched core diffs are surgical (gateway/run.py 14 lines, hermes_state_compression.py 121, hermes_cli/cli_auto_maintenance.py 9); fork-only features verified absent upstream (delegation stack 404s, zero turn_lease occurrences in upstream hermes_state.py); pm atomic-switch updates in v0.22.0 address the fleet's same-commit-rebuild gateway restarts
- acceptance: (1) v0.22.2 tag merged (never v0.22.1); (2) every collision has a documented resolution before merge: sessions.auto_prune default-on (90-day startup deletion) vs fork housekeeping/vacuum gates; session_reset idle/daily retirement; tool renames (todo->todo_list, cronjob->cronjob_manage, process->process_manage); plugin compat import layer removal; one-gateway-per-machine multiplex vs HX002 profile-binding seams; pm-owned envs; Python 3.14 runtime (KittenTTS unavailable); (3) fork features rebased and green: turn-lease focused battery + delegation-stack tests; (4) full_tests differential under the sanctioned CI A/B shape (patch-identical mirror PRs, census union; the v0.21.7 baseline of ~534 CI failures must not grow on the fork-delta leg)
- evidence: compare API stats, per-collision resolution notes in the shipping PR, CI A/B census files, focused-battery logs

### Clear the two JS-lane blockers
- id: `rm-080` | track: reliability | priority: 95.0 | status: candidate
- signals: assess N5/N6 + research R5/R6: run 38951784747 job 117144782849 fails engines-satisfiable (tests-js/engines-satisfiable.test.ts:121,125,218 demand NODE_VERSION= in scripts/install.sh which no longer defines it; install.sh:5 says node is pm's job; package.json:69 declares the ^22.22.0 arm) AND the native build (apps/desktop/electron/native/hud-modifier-monitor-x11.c:2 fatal error X11/Xlib.h); upstream has neither the test (404 @v0.22.2) nor X11 deps in its lane — both fixes are fork-owned; in-repo precedent .github/workflows/install-e2e-run.yml:129-140
- acceptance: (1) the engines contract is re-pointed at pm's node provisioning (or install.sh regains gates for every engines arm) and tests-js/engines-satisfiable.test.ts passes from a clean checkout without network; (2) the JS & TS lane installs libx11-dev/libxi-dev (or otherwise compiles/skips the x11 monitor) and is green on a main push run
- evidence: lane job log showing the x11 monitor compiling and the engines test green; gh run view of the landing commit

### Guard the roadmap render to tracked signals
- id: `rm-081` | track: reliability | priority: 90.0 | status: candidate
- signals: assess N7 (extends closed rm-016/rm-023): the pre-update rm-001/rm-002 cited .worktrees/t_171b1032/* (gitignored scratch, .gitignore:93) and hermes_cli/web_dist/* (untracked build output, .gitignore:97) — 19/20 and 20/20 signals were non-repo paths — and both claimed 'full suite green at HEAD' contradicted by run 38951784747
- acceptance: (1) an in-repo guard test parses ROADMAP.md and fails when any signals/acceptance-cited path is untracked or nonexistent (proven red on the pre-fix render, green after); (2) ROADMAP carries tracked-only signals from here on; renderer-side ignore-respecting scan filed to the autonomy stack
- evidence: guard test red-on-base proof and green run; render diff

### Forward-port gateway host-lock identity if adoption slips
- id: `rm-082` | track: reliability | priority: 88.0 | status: candidate
- signals: research R2: upstream v0.22.2 fixed exactly the class the fleet guards with HX003 — drop argv identity from host rendezvous liveness (c7fa3cbf), reject a recycled PID that only matches start ticks (7934442e), boot-epoch + host-lock liveness (PRs #138594, 91e63f84, 4d984677, 5b416e42, fixes #133744); fleet lineage: a gateway mid-update restart was misread as a critical failure by the external phase2 probe
- acceptance: (1) liveness never infers identity from argv substrings; host-lock/boot-epoch decide; (2) invariant tests are red on base for the recycled-PID and post-reboot-refusal cases and green after; (3) gateway/AGENTS.md HX003 guidance is updated to the new doctrine
- evidence: test battery results + AGENTS.md diff

### Add real coverage for genuinely untested tracked modules
- id: `rm-083` | track: reliability | priority: 85.0 | status: candidate
- signals: supersedes rm-002 (its list was 19/20 scratch-worktree paths); confirmed real gap: .github/scripts/run-workspace-checks.mjs (tracked, no test); acp_adapter/ has 29 test files and is NOT untested — the scratch copy was
- acceptance: a fresh tracked-tree scan produces the cohort of modules with no corresponding test file (listed in the PR); every cohort module gains a test file with at least one passing test run via scripts/run_tests.sh; suite delta green
- evidence: cohort list + per-module passing-test citations

### Decompose tracked complexity hots
- id: `rm-084` | track: reliability | priority: 80.0 | status: candidate
- signals: supersedes rm-001 (its signals were minified web_dist build output); ledgered rm-031: agent/auxiliary_client.py at 8,419 lines and growing (7,630 at the prior assess)
- acceptance: flagged functions decompose below the branch threshold with characterization tests locking behavior; auxiliary_client.py shrinks or carries an explicit per-unit offset plan under the code-health ratchet rules
- evidence: ast branch-count check passes at HEAD; size-ratchet numbers before/after

### Move fork updates to upstream release channels
- id: `rm-085` | track: maintenance | priority: 70.0 | status: candidate
- signals: research R8: upstream v0.22.0 ships tested SemVer channels (releases-not-commits default, --set-channel main escape hatch, labelled rollbacks; PRs #102765/#135847/#135949) while the fork hand-stitches tag ancestry ('chore: stitch v0.21.7 tag ancestry')
- acceptance: fork update docs describe channel selection and rollback; an update dry-run follows the release tag without a stitch commit
- evidence: docs diff + dry-run log

### Post-adoption capability shortlist
- id: `rm-086` | track: capability | priority: 60.0 | status: candidate
- signals: research R9 (fork repo has issues disabled; upstream is the demand pool): fix-first: acp_adapter ImportErrors in the known fleet-host full-suite failure census; upstream top requests #25267 Claude Agent SDK OAuth provider (57+), #18715 remote agent + local tool execution (41+), #5941 Searxng default search (30+), #12238 built-in ~/.hermes backup/versioning (27+), #20510 config cloud-sync (23+)
- acceptance: acp_adapter ImportErrors eliminated from the full-suite census; each capability decision recorded with its upstream issue ref and a fork-fit note
- evidence: census diff + decision notes

### Two low-severity cleanups
- id: `rm-087` | track: maintenance | priority: 40.0 | status: candidate
- signals: assess N8/N9: desktop-bundled-release.yml:2469-2473 failure-path step says 'Upload this package' but its URL can fall back to handoff-windows-universal.json (a manifest, not a package); AGENTS.md sits at 11,996 of its 12,000-char cap
- acceptance: the fallback names an uploadable artifact (or the handoff JSON provably exists at the tag path); the next AGENTS.md addition routes to an area file and the hub stays under cap
- evidence: workflow dry-check; scripts/check size-gate output

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
- `rm-002` Add test coverage for 20 untested module(s) — superseded by rm-083 (19/20 signals were .worktrees scratch paths, not tracked modules)
- `rm-001` Refactor 20 high-complexity function(s) — superseded by rm-084 (all signals were minified hermes_cli/web_dist build output, not source)

<!-- managed by hermes-roadmap render; do not edit by hand -->

# hermes-agent — Roadmap

> Autonomously maintained by the roadmap sync (reliability-first). Items cite reproducible codebase signals; acceptance is proven by cited evidence.

**Vision**: A reliable, customer-friendly repository advanced by evidence-cited roadmap cycles owned by the autonomy loop

**Pillars**: reliability work outranks customer-experience work; every roadmap item cites reproducible codebase signals; acceptance is proven by cited evidence, never claimed

## Fleet context

- upstreams (this repo builds on): .github, agent
- dependents (changes here affect): (host), agent, dashboard, hermes-infra, hermes-stewardship-dashboard, jarvis, maestro, magic-hermes
- graph: evidence-derived (imports/refs/deploy surfaces); advisory

## Open items

### Restore main's required CI checks to green
- id: `rm-078` | track: reliability | priority: 100.0 | status: candidate
- signals: assess 2026-10-17 N1/N2/N3/N4: gh run 38951784747 on 682c8a41a9d has 7 failed lanes incl. ruff enforcement (blocking) + Windows footguns (blocking) + 'All required checks pass (v2)'; main push runs red since 2026-10-08T20:15Z (37838062378); pinned-tool repro: ruff check . -> 134 errors (UP006 x52, RUF100 x16, UP037 x16, PLR0402 x13; tools/delegate_session_tool.py 26, agent/opencode_client.py 23, agent/pi_rpc_client.py 16), scripts/check-windows-footguns.py --all -> 7 findings; tracked ruff.toml shadows pyproject [tool.ruff] (ruff --show-settings proves preview=disabled, pyproject inert); offenders are fork-only (404 upstream @v0.22.2) and upstream main is CI-green under a byte-identical ruff.toml
- acceptance: (1) exactly one ruff config authority survives (ruff.toml XOR pyproject [tool.ruff]) and lint.yml's comment names the real one; (2) ruff check . and scripts/check-windows-footguns.py --all report zero findings on a clean checkout of main; (3) python scripts/check passes on clean main; (4) code-health ratchet covers the delegation stack (tools/delegate_session_tool.py, agent/opencode_client.py, agent/pi_rpc_client.py) so autonomy checkpoints cannot land red; (5) a push run on the landing commit shows both blocking lint lanes and the aggregate gate green
- evidence: pinned-tool outputs at the bumped pin (ruff 0.15.10 -> 0.17.1, baseline re-run in the same change), gh run view <landing> --json jobs, ratchet config diff
- rider (2026-10-22, repository-maintenance cycle:2 run 4f869afa11214872bf0dcca179c7513b roadmap c2bc1a8355d5410796c441b3de9c3334, from assess eae1dec9 F1/F2 + research e5bb23ea): REGRESSION recorded — the cycle-1 single-authority fix did not survive main: salvage 538423b599 kept ruff.toml as the authority (deleting only the dead pyproject block), then ea2f2033f7 deleted ruff.toml on the belief pyproject carried the config, and merge 68cbe2eb53 took the salvage's pyproject side with ruff.toml still deleted — net ZERO ruff config at main 0b47716354 (all three legs re-verified 2026-10-22). Live census: uvx ruff 0.17.1 isolated check -> 42,312 diagnostics; python scripts/check FAILED (no-tmp, ruff); tests/scripts/test_code_health_cli.py 10 reds (FileNotFoundError copying the gone ruff.toml). Repair minted as rm-088; the cycle-1 record's "ruff.toml is the one authority, provably the enforced one" clause is falsified at main and corrected by rm-088 acceptance (4)

### Adopt upstream v0.22.2 (never v0.22.1)
- id: `rm-079` | track: adoption | priority: 98.0 | status: candidate
- signals: research 2026-10-17 R1/R2/R3: upstream shipped v0.22.0/v0.22.1/v0.22.2 past our v0.21.7 base; v0.22.1 was built from the wrong commit (Store 'Connecting' stick) and v0.22.2's known issue is that sessions created under the 0.22.1 gateway can't be deleted; compare v0.21.7...v0.22.2 = 2,983 commits while fork-patched core diffs are surgical (gateway/run.py 14 lines, hermes_state_compression.py 121, hermes_cli/cli_auto_maintenance.py 9); fork-only features verified absent upstream (delegation stack 404s, zero turn_lease occurrences in upstream hermes_state.py); pm atomic-switch updates in v0.22.0 address the fleet's same-commit-rebuild gateway restarts
- acceptance: (1) v0.22.2 tag merged (never v0.22.1); (2) every collision has a documented resolution before merge: sessions.auto_prune default-on (90-day startup deletion) vs fork housekeeping/vacuum gates; session_reset idle/daily retirement; tool renames (todo->todo_list, cronjob->cronjob_manage, process->process_manage); plugin compat import layer removal; one-gateway-per-machine multiplex vs HX002 profile-binding seams; pm-owned envs; Python 3.14 runtime (KittenTTS unavailable); (3) fork features rebased and green: turn-lease focused battery + delegation-stack tests; (4) full_tests differential under the sanctioned CI A/B shape (patch-identical mirror PRs, census union; the v0.21.7 baseline of ~534 CI failures must not grow on the fork-delta leg)
- evidence: compare API stats, per-collision resolution notes in the shipping PR, CI A/B census files, focused-battery logs
- rider (2026-10-22, repository-maintenance cycle:2 run 4f869afa11214872bf0dcca179c7513b roadmap c2bc1a8355d5410796c441b3de9c3334, from research e5bb23ea): target refreshed — upstream shipped v0.22.3 and v0.22.4 on 2026-10-21 (canary already past v0.22.4 by 2026-10-22); the window is HEAD..v0.22.4 = 6013 commits / 5277 files (+400,949 −104,010), v0.22.3 alone ~620 PRs / 4,206 files. Decision inputs: (a) tools approval_detection is untouched across v0.21.7..v0.22.4 — the fork-first bypass fix (rm-092) is adoption-independent; (b) v0.22.4 still ships BOTH ruff.toml (473 lines) and a pyproject tool.ruff block — adoption does not cure the authority regression, so rm-088 lands first or the adoption merge settles it in-change; (c) the v0.22.2 collision inventory needs a v0.22.3/.4 delta pass before any merge; (d) the v0.22.2 gateway host-lock family is unchanged through v0.22.4, so rm-082's trigger is unchanged

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
- rider (2026-10-22, repository-maintenance cycle:2 run 4f869afa11214872bf0dcca179c7513b roadmap c2bc1a8355d5410796c441b3de9c3334, from research e5bb23ea): currency re-verified — the host-lock/boot-epoch family (c7fa3cbf, 7934442e, PRs #138594/91e63f84/4d984677/5b416e42) is unchanged through upstream v0.22.4, so this row fires as-is if adoption slips a cycle

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
- rider (2026-10-22, repository-maintenance cycle:2 run 4f869afa11214872bf0dcca179c7513b roadmap c2bc1a8355d5410796c441b3de9c3334, from research e5bb23ea first-hand release-body census): the v0.22.x demand pool is now measured — v0.22.0 ships first-launch setup chat, connectors via the tool gateway (Linear/Notion), one-click local models on llama.cpp, stable SemVer release channels (ties rm-085), signed MSIX/Store desktop, password-manager sign-in, Bot Screen, one gateway + one backend per machine across profiles, live subagent steering, plan-aware model picker, i18n catalog (16 languages); v0.22.3 adds MCP live progress, plugin-declared OAuth clients, refreshed CLI layout, opt-in session auto-prune. Each adoption decision should cite its upstream release note + PR set as the demand evidence

### Two low-severity cleanups
- id: `rm-087` | track: maintenance | priority: 40.0 | status: candidate
- signals: assess N8/N9: desktop-bundled-release.yml:2469-2473 failure-path step says 'Upload this package' but its URL can fall back to handoff-windows-universal.json (a manifest, not a package); AGENTS.md sits at 11,996 of its 12,000-char cap
- acceptance: the fallback names an uploadable artifact (or the handoff JSON provably exists at the tag path); the next AGENTS.md addition routes to an area file and the hub stays under cap
- evidence: workflow dry-check; scripts/check size-gate output

### Repair the ruff-authority regression (zero config at main)
- id: `rm-088` | track: reliability | priority: 97.0 | status: candidate
- signals: assess 2026-10-22 cycle:2 at 0b47716354 — the three-leg composite (salvage kept ruff.toml authority, then ea2f2033f7 deleted ruff.toml while restoring a pyproject tool.ruff block, then merge 68cbe2eb53 took the salvage pyproject side with ruff.toml still deleted) leaves ZERO ruff config: uvx ruff 0.17.1 isolated check -> 42,312 diagnostics; python scripts/check FAILED (no-tmp, ruff); 10 reds in tests scripts test_code_health_cli.py (FileNotFoundError copying ruff.toml); the lint.yml blocking-lane comment still names the deleted ruff.toml as the single authority; the pin ruff 0.17.1 in pyproject is itself current — this is a config-elimination regression, not version drift
- acceptance: (1) exactly one ruff authority exists on main and ruff --show-settings proves it enforced, with the lint.yml comment naming the real one in the same change; (2) ruff check . zero findings, python scripts/check 12/12, and tests scripts test_code_health_cli.py fully green on a clean checkout; (3) a push run on the landing commit shows the ruff enforcement lane green; (4) a config-presence regression test fails when neither ruff.toml nor a pyproject tool.ruff block exists (red on the regressed base), and the falsified cycle-1 authority claim carries a dated correction rider
- evidence: landing diff (git show); local pinned-tool outputs; the CI run URL of the landing commit

### Teach the CI-routing test evaluator the workflows' real expressions
- id: `rm-089` | track: reliability | priority: 93.0 | status: candidate
- signals: assess 2026-10-22 F3 at 0b47716354 — tests ci test_update_ci_routing.py 78 failed / 28 passed because the evaluator at tests ci _gha_expr.py line 190 raises Unsupported for the startsWith() calls the tests-job routing (ci.yaml lines 142-146) and pm-bundle.yml actually use; the routing battery is red on main today
- acceptance: (1) the evaluator implements the grep-derived census of expression functions the tracked workflows actually use (at minimum startsWith and endsWith per the GitHub expressions reference); (2) scripts/run_tests.sh tests ci test_update_ci_routing.py fully green on a clean checkout; (3) no workflow simplification to dodge the evaluator — the evaluator meets the workflows, not the reverse
- evidence: battery output before/after; the function census list in the PR

### Make the merge gate real (required checks + needs completeness)
- id: `rm-090` | track: reliability | priority: 91.0 | status: candidate
- signals: assess 2026-10-22 F1/F4/F5/F9 + research at 0b47716354 — the branches main protection rule requires NOTHING (empty required_status_checks, enforce_admins off, no required PR reviews; gh api), and PR #511 merged with 7 red lanes; all-checks-pass.needs omits tests-standard and e2e-desktop-core-standard (tests ci test_stable_release_graph.py line 165 red); tests ci test_classify_changes.py line 608 desynced from the conductor-tests routing at ci.yaml line 147; the canary lane is red at canary-release.yml line 29 (run 39778226947, job Tag, draft, and start the canary build)
- acceptance: (1) branch protection on main requires the blocking set (ruff enforcement, Windows footguns, tests lanes, the aggregate gate) with enforce_admins on, and a red-lane probe PR is provably unmergeable (recorded); (2) all-checks-pass.needs covers every status-bearing job and tests ci test_stable_release_graph.py is green; (3) tests ci test_classify_changes.py green against the real routing; (4) the canary job failure is triaged to root cause with a fix or a filed note
- evidence: protection JSON after the change; the probe PR outcome; battery greens; canary triage note

### Repair the pm extras-default regression (legacy all-extra injection + bare-sync contract)
- id: `rm-091` | track: reliability | priority: 89.0 | status: candidate
- signals: assess 2026-10-22 cycle:2 first-hand batteries at 0b47716354 — legacy_selection in pm extras (line 299) returns the carry with 'all' prepended unconditionally (reached from pm install lines 763-766 whenever recorded extras are falsy), so any project without an 'all' extra hard-fails uv sync: tests pm test_plugin_survival_contract.py 7 reds + test_restart_needed.py 1 red, all InstallError Extra 'all' is not defined; and 0a977bcef2 (2026-10-19) changed bare pm sync to default to no extras while tests pm test_install_default_closure.py still asserts the old all-default contract (3 reds) — 11 red tests on main
- acceptance: (1) the legacy carry intersects the package's declared extras before syncing (or 'all' only when actually declared) and all 8 injection reds go green; (2) the bare-sync default is decided once and code + tests state it (the 3 contract reds updated deliberately, not deleted); (3) scripts/run_tests.sh tests pm fully green on a clean checkout; (4) upstream's neighboring pm fixes (b357b96bd9 empty-pyproject membership, 8d3b5ab544 npm PATH) checked absorb-before-write
- evidence: battery outputs before/after; the bare-sync default decision note

### Expand approval detection past variable indirection (fork-first, upstreamable)
- id: `rm-092` | track: security | priority: 87.0 | status: candidate
- signals: assess 2026-10-22 F6 live probe at 0b47716354 — detect_dangerous_command (tools approval_detection.py line 1548) leaves 7 variable-indirection shapes unflagged (assignment-then-use forms like F=-delete; find . $F and quoted X=rm; "$X" -rf) while the literal forms are flagged; upstream has ZERO commits to the file across v0.21.7..v0.22.4 and no tracking issue — the class is unpatched upstream too, so this is fork-first work eligible for an upstream PR (SECURITY.md 3.2: ordinary public work)
- acceptance: (1) variable-indirection expansion resolves assignments before classification and every probe shape is flagged, with invariant tests proven red on base; (2) a false-positive census over the repo's own scripts and skills shows no benign-command regression; (3) the fix follows the contribution rubric (no new core surface; behavior-contract tests; E2E with a temp HERMES_HOME where applicable); (4) an upstreamability note records the patch shape for the upstream PR
- evidence: probe outputs before/after; red-on-base proof; false-positive census

### Refresh pinned uv (0.12.3 -> 0.13.5)
- id: `rm-093` | track: maintenance | priority: 25.0 | status: candidate
- signals: research 2026-10-22 — pm lock.json still carries uv 0.12.3 download URLs while astral-sh/uv latest is 0.13.5; the ruff pin 0.17.1 is current (no action owed)
- acceptance: pin bump lands via hermes pm lock with lockfiles committed per the pm policy and the install-e2e lanes green on the bump
- evidence: pm lock diff + lane run URLs

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

## Cycle log — cycle 1 (post-Extension append)

### Cycle 1 (2026-10-17, conductor run a82f2f4c8df945dda13a380463763887) — batch rm-078 + rm-080 + rm-081 + rm-087 (stretch), "restore trustworthy CI on main"
- status: all three units + stretch implemented and locally validated; the 43-path delta (+444/−342) is held at salvage commit 538423b599030d9b068e7ccda4e89b5c8f845cf0 in run worktree run-a82f2f4c8df9-a82f2f4c (base 682c8a41a9d), awaiting the review/shipping stages — no review or shipping outcome is claimed here; rm-078 acceptance clause (5) (a green push run on the landing commit) is by construction a post-ship observation for the next cycle's assessment
- rm-078 → addressed: ruff config single-sourced (dead pyproject [tool.ruff] block deleted — ruff.toml is the one authority, provably the enforced one — and the lint.yml comment now names it); pin 0.15.10 → 0.17.1 re-baselined in the same change (pyproject.toml + uv.lock): ruff 0.17.1 check . reports All checks passed against the fleet's 134-violation 0.15.10 baseline (top files tools/delegate_session_tool.py 26, agent/opencode_client.py 23); all 7 Windows footgun sites cleared (scripts/check-windows-footguns.py --all → 0 findings across 1970 files); delegation stack (tools/delegate_session_tool.py, agent/opencode_client.py, agent/pi_rpc_client.py) registered in the scripts/code_health ratchet so autonomy checkpoints cannot land red
- rm-080 → addressed: tests-js/engines-satisfiable.test.ts re-pointed at pm's node provisioning contract (install.sh keeps no NODE_VERSION gates; pm owns node per install.sh:5 and the engines arms), and the JS & TS lane installs libx11-dev/libxi-dev mirroring .github/workflows/install-e2e-run.yml:129-140 so the hud-modifier-monitor-x11 native build compiles
<!-- no-tmp: ok — historical record of where the cycle-1 pre-fix render was captured; the durable copy is the cycle-1 spool artifact, not this path -->
- rm-081 → addressed: guard test tests/ci/test_roadmap_tracked_signals.py (3 tests) fails whenever a structured signals/acceptance kind:path entry cites an untracked or nonexistent path; red-on-base proven against the captured pre-fix render (24 phantom tracked paths → AssertionError; pre-state at /tmp/assess-a82f2f4c/ROADMAP-pre.md and the 91197ea9 roadmap diff)
- rm-087 (stretch, text half) → addressed: .github/workflows/desktop-bundled-release.yml:2469-2473 failure-path step now names the real fallback artifact (handoff manifest vs package); the AGENTS.md-headroom half is informational only (no file change)
- validation (recorded outcomes, not re-run in compound): targeted battery scripts/run_tests.sh --file-timeout 1200 over 54 files (changed tests + direct importers + workflow-parser tests; the seeded fast-mode selector answers fallback=full whenever pyproject.toml/uv.lock is in the delta, so the repo-canonical battery is the sanctioned targeted proof) → 930 passed / 3 failed / 1 skipped in 110.4s, all 3 battery failures attributed pre-existing on a detached 682c8a41a9d base worktree (same 3 FAILED ids); python scripts/check 12/12 ok; code-health 36 flagged files, 0 blocking; full_tests DIFFERENTIAL PASSED under the sanctioned CI A/B shape — verbatim local gate leg RC 124 (7200s typed cap, ~54% census, envelope ~/.hermes/local-validation-gate/results/result-3733375-474085398.json) plus mirror PRs #13 (ctrl, run 39026207808) / #15 (head, run 39040043092) with git patch-id 114adb1c1d357c3b0410770fbe04a6c878c9f499 equal on both sides; final-status census ctrl 480 / head 472 final-failed ids, head-only 0, ctrl-only 8 (retry-flake class, itemized in the verdict doc at /home/agent/.hermes/conductor-delegate-spool/e0b93640-fulltests/fulltests-verdict.md); validation digest validation:v1:7bef0d28fd5657a75787bd7f1d19f0bebbbaa41fe736e2d47f7b6585d63599c4 re-derived byte-identical at dispatch

### Cycle 1 lessons (prevention rules for future cycles)
- Prove debt fork-locality before scheduling it as an adoption side-effect: byte-identical ruff.toml + a green upstream run (e7e839a5f4) + offenders 404 upstream ⇒ the 134-violation lint debt is fork-local and no upstream merge will clear it; it needed its own reliability unit (it got one)
- A ruff minor bump is a semantic change: 0.15 defaults (E4/E7/E9/F) silently gained I001/UP by 0.17, so config single-sourcing, the pin bump, and the full-tree re-baseline must land as ONE change or the pinned venv, uvx invocations, and CI disagree; synthetic/scratch trees running the pinned ruff need the repo's ruff config copied in or they self-flag
- Census reality on retrying runners: a naive grep-FAILED union overcounts because attempt-1 failures of retry-passed files stay in the job log; the authoritative census is last-attempt-per-file from the runner progress lines, and GitHub's per-line timestamp prefixing breaks any two-space banner anchor (analyzer kept at /home/agent/.hermes/conductor-delegate-spool/e0b93640-fulltests/census/final-status-analyzer.py)
- For any batch touching pyproject.toml or uv.lock, the seeded targeted selector is useless (always fallback=full): run the repo-canonical run_tests.sh battery over changed test files + direct runtime importers + tests parsing changed workflows, and A/B-attribute every battery failure on a detached base worktree before calling it pre-existing
- Stewardship request surfaces must be bare repo-relative paths (per-entry ≤1024 chars, ≤128 entries): annotated file:line paragraphs blow ChangeUnit.allowed_scope and the fold rejects with a validation error — put evidence in the request summary + companion markdown instead
- Infra-reap salvage pattern: a lost PhaseResult envelope is a transport artifact, not lost work — land verified content as a patch-id-equal salvage commit (f79c55ce's full_tests → adopted via 538423b/e0b93640) and re-verify both legs before adopting; a fold rejection for a missing changed-surfaces attestation is re-emittable with zero tree churn (implement 09ca7176 → b1910194)
- Roadmap compound appends do not survive renderer refreshes in tracked history (git log -S 'Cycle log' -- ROADMAP.md is empty); the durable cycle record is the .conductor/compound/ diff artifact plus the spool verdict docs — keep writing both every cycle

### Cycle 2 candidate seeding (from cycle-1 evidence, pre-review)
- rm-079 (adopt upstream v0.22.2, never v0.22.1) is the seeded headliner: deliberately sequenced after this batch so it adopts onto green lint lanes and census deltas attribute cleanly; own-cycle scale (2,983 commits, 7 documented collision resolutions) using the CI A/B full_tests harness proven this cycle
- rm-082 fires only if adoption slips (the same host-lock fixes arrive wholesale in the merge); rm-083 and rm-084 prefer the post-adoption tree (v0.22.2 moves module layout — covering or decomposing pre-merge modules risks wasted work); rm-085 and rm-086 are gated on rm-079 mechanics
- Post-ship verification debt for the next assessment to carry: rm-078 acceptance (5) needs the landing push run's blocking lanes green; the v0.21.7-lineage baseline (~534 CI / ~780 fleet-host pre-existing failures) still owns the python-test lanes; the 8 ctrl-only flaky census ids are the census-drift watch list
- Renderer-side ignore-respecting scan (rm-081 acceptance tail) remains filed to the autonomy stack, unminted as an item

### Cycle 2 update (2026-10-22, run 4f869afa11214872bf0dcca179c7513b roadmap c2bc1a8355d5410796c441b3de9c3334, from assess eae1dec9 + research e5bb23ea)
- corrections to the cycle-1 record (history preserved, claims corrected): the cycle-1 batch is no longer "awaiting the review/shipping stages" — it landed on main via 68cbe2eb53 and successors; however the rm-078 authority claim is falsified at main by the composite regression (see the rm-088 row and its rm-078 rider); the no-tmp literal on the cycle-1 rm-081 line is now marked rather than deleted (historical capture-site record)
- minted this update: rm-088 (ruff-authority regression repair), rm-089 (CI-routing evaluator expressions), rm-090 (merge-gate enforcement + needs completeness + canary triage), rm-091 (pm extras-default regression, 11 reds), rm-092 (approval-detection variable indirection, fork-first), rm-093 (uv pin refresh); riders recorded on rm-078 (regression), rm-079 (target refresh to v0.22.4 + decision inputs), rm-082 (currency through v0.22.4), rm-086 (v0.22.x demand-pool census)
- re-sequencing recommendation from research: the CI-trust batch core is rm-088 + rm-089 + rm-090 (+ the roadmap-hygiene halves already handled here), then rm-091 as the correctness batch; rm-092 is adoption-independent (upstream unpatched through v0.22.4); rm-079 re-baselined onto v0.22.4 with its collision inventory refreshed before any merge; rm-093 rides any touched-pin change
- evidence expectations carried forward: every new row's acceptance cites clean-checkout battery greens and a landing push run where relevant — no acceptance is claimed without its cited evidence

# hermes-agent — Roadmap

> Autonomously maintained by the roadmap sync (reliability-first). Items cite reproducible codebase signals; acceptance is proven by cited evidence.

**Vision**: A reliable, customer-friendly repository advanced by evidence-cited roadmap cycles owned by the autonomy loop

**Pillars**: reliability work outranks customer-experience work; every roadmap item cites reproducible codebase signals; acceptance is proven by cited evidence, never claimed

## Fleet context

- upstreams (this repo builds on): .github, agent
- dependents (changes here affect): (host), agent, dashboard, hermes-infra, hermes-stewardship-dashboard, jarvis, maestro, magic-hermes
- graph: evidence-derived (imports/refs/deploy surfaces); advisory

## Open items

### Add test coverage for the 5 verified-untested modules
- id: `rm-002` | track: reliability | priority: 100.0 | status: candidate
- signals: re-scoped 2026-10-09 at HEAD 1a5b8a4faf7 (phantom `.worktrees/t_171b1032/**` and untracked-`web_dist` paths dropped — see rm-036): reliability.no_tests:acp_adapter/content.py, reliability.no_tests:acp_adapter/__main__.py, reliability.no_tests:.github/scripts/run-workspace-checks.mjs, reliability.no_tests:agent/activity_tracking.py, reliability.no_tests:agent/agent_runtime_helpers.py (per-topic search over tests/ returns 0 matches for each; acp_adapter auth/commands/edit_approval/entry/events/model_catalog/permissions/provenance/server/session/tools are already covered, as are agent/account_usage, acp_openai_bridge, agent_init)
- acceptance: Each of the 5 modules has a corresponding test file with at least one passing, invariant-style test (behavior contract, not a change-detector)
- evidence: full suite green (scripts/run_tests.sh) at HEAD; conductor validation digest validation:v1:<sha> recorded in the shipping PR

### Adopt upstream v0.21.6 onto the fork release line
- id: `rm-033` | track: adoption | priority: 92.0 | status: candidate
- signals: fork base v2026.9.24 (v0.21.5) is 37 commits ahead on the fork-minimal line; upstream v0.21.6 published 2026-10-08 (tag f27cdbce5ab63eafe8633b293a75151409da5769; window = 2,106 merged PRs, 8,342 changed files, +772,490/−225,600); collision preview: 108 of 174 fork-changed files also changed upstream in-window (incl. agent/auxiliary_client.py and 19 .github/workflows/*); upstream's new pm/ subsystem ('hermes pm lock', upstream AGENTS.md:135) is absent from the fork base; #477 classified the three install-e2e legs as pre-pm known-failures expected to self-heal at next adoption. Cycle-2 refresh (2026-10-10): v0.21.7 is already at rc.6 (tag rc.6-v0.21.7 = cf23a1a5cc3 = upstream/main tip, 331 commits past v0.21.6) — adoption window decision point; v0.21.6 additionally ships SIX security-fix classes whose vulnerable surfaces are verified present at HEAD 1a5b8a4faf7: dashboard X-Forwarded-For first-hop trust (hermes_cli/dashboard_auth/request_utils.py:20-21; rate-limit reset, TRA-725/#133367), native sign-in loopback-redirect flow (hermes_cli/dashboard_auth/native_flow.py:42; #130685), no request-body cap on public /auth/ routes (hermes_cli/dashboard_auth/routes.py; #133370), unbounded auth audit writes (hermes_cli/dashboard_auth/audit.py; #133369), untrusted-repo git-filter execution before first prompt (#130661), email From quoted-display-name allowlist bypass (#125212)
- acceptance: v0.21.6 tag (or v0.21.7 if tagged by execution time — record which) merged onto the fork release line with every logical fork change traceable post-merge (git merge-tree conflict dry-run census recorded before merging; conflicts resolved file-by-file, fork semantics preserved); pm/ workflow reconciled (AGENTS.md pinning instruction, CI jobs invoking bare `uv`); the three #477 install-e2e known-failure classes re-run and verified healed or re-classified with new evidence (falsifiable check, not assumption); the four dashboard-auth surfaces post-merge covered by the adopted upstream tests (XFF parse, body cap, audit bound, native-flow redirect) — linked receipts; quarantine-compatible dependency refreshes folded (mcp 2.2.0→2.3.0, pydantic 2.13.5→2.14.0, prompt-toolkit 3.0.52→3.0.53, upper bounds kept); full suite green
- evidence: adoption PR records tag sha, merge-tree before/after census, install-e2e before/after run links, dashboard-auth test receipts; conductor validation digest validation:v1:<sha> recorded in the shipping PR

### Migrate desktop Electron 40.10.2 to ≥41.9.1 (GHSA-r4w5-6pfg-jxp5)
- id: `rm-035` | track: security | priority: 88.0 | status: candidate
- signals: apps/desktop/package.json:181 (dep) and :194 (build.electronVersion) both 40.10.2; root package.json allowScripts['electron@40.10.2']; package-lock.json apps/desktop/node_modules/electron = 40.10.2; GHSA-r4w5-6pfg-jxp5 fixed only in 40.10.6/41.9.1; npm registry current 44.7.0; upstream/main verified still at 40.10.2 (cannot ride adoption — fork-led per the #48 port-security-fixes doctrine; also a contribute-upstream candidate). Cycle-2 re-verification (2026-10-10): all anchors still 40.10.2 at HEAD 1a5b8a4faf7
- acceptance: all 4 anchors moved together (dep + electronVersion + package-lock entry with its dependencies list re-resolved via npm ci, never --package-lock-only hand-edit + root allowScripts); both guard vitest files updated and green (tests-js/allow-scripts-sync.test.ts, apps/desktop/electron/desktop-electron-pin.test.ts); win32 validation receipt (windows-venv-e2e lane or windows runner) proving no ERR_DLOPEN_FAILED from the native-napi @electron/get flip; desktop smoke green
- evidence: PR carries the 4-anchor diff, lock diff showing re-resolved dependency list, win32 run link, and a GHSA re-scan (osv-scanner) that no longer flags the advisory; conductor validation digest validation:v1:<sha>

### Decompose agent/auxiliary_client.py below the god-file threshold
- id: `rm-034` | track: reliability | priority: 80.0 | status: candidate
- signals: reliability.god_file:agent/auxiliary_client.py = 8,201 lines / 322 top-level defs / 24 classes (largest file in the repo; 4x the ~2,000-line split signal in AGENTS.md; absent from the documented facade-family list) while 9 auxiliary_client_*.py siblings already establish the decomposition pattern; sequencing constraint: the file is inside the rm-033 adoption collision set — execute immediately AFTER rm-033 lands and re-derive the fork delta first. Cycle-2 census (2026-10-10): 48 files >2k lines at HEAD (stable population); upstream alignment confirmed — upstream issue #78647 'Repo-wide godfile eradication: residual 2K tasks' is upstream's most-commented open issue (82 comments), so extractions remain dual-community welcome
- acceptance: facade below 2,000 lines with topical siblings per the <stem>_<topic> convention; no function >300 lines / cyclomatic complexity >30; evals/codebase_navigability/static_metrics.py report attached before/after; behavior locked by the existing suite (test edits only where patch-target bindings must follow the defining module per AGENTS.md)
- evidence: static-metrics before/after in the PR; full suite green; conductor validation digest validation:v1:<sha>

### Move blocking media I/O off the event loop (shared helper + 6 sites)
- id: `rm-040` | track: reliability | priority: 78.0 | status: candidate
- signals: cycle-2 adversarial assess at HEAD 1a5b8a4faf7 (AST blocking-I/O-in-async census over gateway/hermes_cli/tui_gateway/tools/agent/cron/acp_adapter: 104 lexical hits, manually triaged; census artifact in the run's assess evidence) found on-loop I/O with in-repo correct precedents: gateway/platforms/weixin.py:1134/:1137/:1142 (async _send_file: full read_bytes + hashlib.md5 + AES-128-ECB encrypt on the gateway event loop, no outbound size cap), tools/vision_tools.py:992-994 (_materialize_video write_bytes of whole video payloads on the loop while the same file's image path :551 correctly awaits asyncio.to_thread), gateway/platforms/qqbot/adapter.py:1276-1277 (wav read_bytes + os.unlink on the loop), gateway/platforms/whatsapp_cloud.py:655-661 (inbound media fully buffered from blob_resp.content with no cap, then write_bytes on the loop), hermes_cli/web_routers/files.py:599 (shutil.rmtree directly in async delete while sibling endpoints dispatch via hermes_cli/web_routers/_common.py:40-45 scoped_to_thread), gateway/relay/media.py:103-110 (upload path fully reads attachment bytes before the MEDIA_MAX_BYTES check; the download side already pre-checks Content-Length at :165 to mirror)
- acceptance: one shared helper (size-cap + to_thread dispatch) adopted at all 6 sites (or per-site to_thread where a helper does not fit, justified per site); relay upload rejects oversize via Content-Length pre-check before buffering; per-site behavior tests (no source-reading, no change-detectors) proving cap enforcement and executor dispatch (e.g. monkeypatched executor capture); platform/relay/files suites green via scripts/run_tests.sh; no new HERMES_* env vars (caps are code constants per the config.yaml doctrine)
- evidence: per-site diffs plus census before/after re-run showing the 6 sites cleared; invariant-test listings; full suite green; conductor validation digest validation:v1:<sha> recorded in the shipping PR

### Verify and safely extract the managed-Node zip
- id: `rm-041` | track: security | priority: 74.0 | status: candidate
- signals: hermes_constants.py:596-632 _stage_windows_node_zip downloads the managed Node (major 22, hermes_constants.py:488) zip with no SHASUMS.txt signature verification and calls archive.extractall() at :629 with no zip-slip/symlink defense before the extracted tree is executed; the in-repo bar already exists: hermes_cli/update_cmd_zip.py _extract_zip_safely; upstream is actively reworking adjacent Node paths in the v0.21.6 window (73162b00eef 'Desktop-only Node dependency failure no longer blocks the TUI and web UI') — coordinate with rm-033 sequencing
- acceptance: zip sha256 verified against SHASUMS.txt fetched from the same pinned dist root before extraction; extraction via a safe-extract routine (member path-escape + symlink rejection) shared with or mirroring update_cmd_zip._extract_zip_safely; tamper tests proven red-then-green (wrong sha256, zip-slip member, symlink member each rejected); install-e2e legs covering Node staging still green
- evidence: red/green tamper-test receipts; full suite green; conductor validation digest validation:v1:<sha>

### Guard the roadmap render against phantom signals
- id: `rm-036` | track: tooling | priority: 65.0 | status: candidate
- signals: ROADMAP.md open items at HEAD 1a5b8a4faf7 cited `.worktrees/t_171b1032/**` (directory absent from the canonical tree) and `hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js` (0 tracked files; minified build output) as reliability signals; recurrence precedent: rm-015 superseded rm-002's phantom list once before, and the closed guards rm-016/rm-023 did not root-cause the scanner
- acceptance: the render pipeline validates every signal path against `git ls-files` (existence) plus artifact exclusions (web_dist, .worktrees, node_modules, *.min.js / vendored bundles) before emitting an item; a regression test feeds a dirty-environment scan (worktree dir + built web_dist present) and asserts the render contains zero phantom paths; rm-002/rm-001-class items can no longer be derived from absent paths
- evidence: test file plus green run in the shipping PR; a clean-scan re-render with zero absent paths attached

### Fetch the base ref in the lockfile-diff CI lane
- id: `rm-042` | track: ci | priority: 58.0 | status: candidate
- signals: .github/workflows/lockfile-diff.yml:55 computes BASE_SHA=git merge-base "origin/${{ github.base_ref }}" HEAD, but actions/checkout never fetches ephemeral conductor/ci-base-* base refs — structural exit-128 red on every ephemeral validation PR (proven on fork PRs #470 and #471: 'fatal: Not a valid object name origin/conductor/ci-base-…'); the lane header declares itself non-blocking review signal yet reddens the checks board; fix is lane-side and fork-only
- acceptance: lane explicitly fetches the PR base ref (checkout with ref: ${{ github.base_ref }} in a pre-step, or an explicit git fetch refspec) before computing merge-base; receipt on the next ephemeral PR (or a deliberate test PR) showing the lane green or cleanly skipped; no behavior change for normal PRs (diff still computed against the true base merge-base); fork repo only, never upstream
- evidence: workflow diff plus before/after job links on an ephemeral PR; conductor validation digest validation:v1:<sha>

### Sync the plugin catalog with upstream and add a drift check
- id: `rm-037` | track: ecosystem | priority: 50.0 | status: candidate
- signals: fork carries 293 plugin-catalog YAMLs vs upstream/main 510 (measured 2026-10-09); upstream cadence ~15 entries/day (281 catalog-prefixed commits in the v0.21.5→v0.21.6 window); upstream continues core-to-plugin extraction (Spotify moved to the catalog in-window), so catalog freshness increasingly gates feature reach
- acceptance: catalog synced with the adopted upstream tag (rides rm-033) or via a standalone scripted sync; sync is additive-only for third-party entries (fork-local YAMLs preserved); CI drift gate compares the fork catalog set against the upstream tag and fails when drift exceeds 25 entries
- evidence: sync PR with add/delete counts; CI job link showing the drift gate red on the current 217-entry gap and green post-sync

### Convert the three source-reading tests to behavior tests
- id: `rm-043` | track: tests | priority: 48.0 | status: candidate
- signals: tests/hermes_cli/test_kanban_wave12_ghost_dispatch.py:109-112, tests/tools/test_terminal_config_env_sync.py:60-61, and tests/e2e/core/upgrade/test_stale_base_guard.py:107-108 assert on inspect.getsource() text, violating the repo's own AGENTS.md ban ('never read source code in tests'); the sanctioned replacement pattern is documented in-tree at tests/gateway/test_hygiene_failure_cooldown_ladder.py:244-251 (extract the logic, test behavior); population is churning (3 previously-flagged sites were fixed since the last census while 2 new ones appeared — the ban needs enforcement or recurring sweeps)
- acceptance: zero inspect.getsource-based assertions remain under tests/ (grep receipt `grep -rn 'inspect.getsource' tests/` → 0); each converted test asserts behavior of extracted/importable logic or exercises the real code path, passing at HEAD; where feasible the guard intent is preserved (test still fails when the guarded property is deliberately broken — red-on-broken receipt)
- evidence: grep before/after; converted-test runs; full suite green via scripts/run_tests.sh

### Refresh stale top-level documentation
- id: `rm-003` | track: reliability | priority: 43.0 | status: candidate
- signals: reliability.stale_doc:README.md
- acceptance: Docs regenerated/updated; staleness detector reports 0 signals
- evidence: inference.stale_docs returns [] for the repo

### Enforce the indicator-style cross-language contract
- id: `rm-038` | track: reliability | priority: 35.0 | status: candidate
- signals: hermes_constants.py:23-25 carries only a '# Keep in sync' comment against ui-tui/src/app/interfaces.ts:75-77; tests/hermes_cli/test_indicator_command.py:125-130 asserts the Python side alone; no Python or TS test compares the two languages' style lists (verified by search over tests/, ui-tui/, apps/desktop/)
- acceptance: single source of truth (generated constant emitted to both surfaces, or a data-driven contract test that does NOT read .ts source text per the no-source-reading rule); both surfaces provably enumerate identical styles and default; the contract test proven red by temporarily desyncing one side
- evidence: red/green receipts in the PR; full suite green

### Remove the invalid noqa directive in tools/lazy_deps.py
- id: `rm-039` | track: hygiene | priority: 25.0 | status: candidate
- signals: tools/lazy_deps.py:527 carries `# noqa: subprocess-stdin` — not a valid rule code; ruff 0.15.10 emits 'Invalid `# noqa` directive' on every lint run and the directive suppresses nothing
- acceptance: directive removed (or replaced with a valid code if a suppression is genuinely needed); `ruff check` over the product tree emits zero invalid-noqa warnings; no behavior change
- evidence: ruff before/after output in the PR; suite spot-check green

### Memoize dashboard CSS serving
- id: `rm-044` | track: performance | priority: 22.0 | status: candidate
- signals: hermes_cli/web_server_dashboard.py:194-198 serve_css re-reads CSS from disk and runs a url()-rewrite replace chain on every request for assets served with immutable Cache-Control headers (no memoization of the small rewritten payload per prefix)
- acceptance: rendered payload memoized per (file, prefix) keyed by mtime+size (or invalidated on web_dist rebuild); a behavior test asserts the file is read once across repeated requests (mocked read or tmp fixture) and the rewrite output is unchanged; dashboard smoke green
- evidence: test + before/after read-count receipt in the PR; suite green

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
- `rm-001` Refactor 20 high-complexity functions — superseded by rm-034 (all flagged signals were hermes_cli/web_dist build artifacts absent from the canonical tree; the real complexity hot is agent/auxiliary_client.py)

<!-- managed by hermes-roadmap render; do not edit by hand -->

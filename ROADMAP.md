# hermes-agent — Roadmap

> Autonomously maintained by the roadmap sync (reliability-first). Items cite reproducible codebase signals; acceptance is proven by cited evidence.

**Vision**: A reliable, customer-friendly repository advanced by evidence-cited roadmap cycles owned by the autonomy loop

**Pillars**: reliability work outranks customer-experience work; every roadmap item cites reproducible codebase signals; acceptance is proven by cited evidence, never claimed

## Fleet context

- upstreams (this repo builds on): .github, agent
- dependents (changes here affect): (host), agent, dashboard, hermes-infra, hermes-stewardship-dashboard, jarvis, maestro, magic-hermes
- graph: evidence-derived (imports/refs/deploy surfaces); advisory

## Open items

### Close the variable-built-word bypass in the terminal approval gate
- id: `rm-028` | track: reliability | priority: 100.0 | status: candidate
- signals: assess probe at HEAD c4da06121c — `detect_dangerous_command("F=-delete; find . $F") == (False, None, None)` while literal `find /tmp -delete` is flagged; same for `D=-delete find $D /`, `R=rm; find . | xargs $R -f`, `V='-exec rm {} ;'; find / $V`, `find . "${F}"`; comment `tools/approval_detection.py:330-331` admits `$var`-built words are uncovered while `$(...)` IS simulated
- acceptance: the approval lexer tracks simple `NAME=value` assignments the same way it already simulates command substitution, so variable-built destructive words resolve before rule matching; the five probe strings above all require approval; existing literal positives/negatives are unchanged (new invariant tests, ≥5 cases, proven red on base first)
- evidence: new invariant tests added beside the existing gate tests (`tests/tools/test_approval.py` / `tests/hermes_cli/test_approvals_test.py`) pass via `scripts/run_tests.sh` at the fix commit

### Pin local-runtime engine downloads (sha256) and refresh the llama.cpp engine tag
- id: `rm-029` | track: reliability | priority: 95.0 | status: candidate
- signals: `hermes_cli/local_runtime/binaries.py:276-314` `expected_sha256` optional and "without pins the computed hash is recorded"; zero callers pass pins (`bootstrap.py:328`, `web_routers/local_models.py:671,776`); `catalog.json` contains 0 sha256 fields; engine pin `b10964` = llama.cpp v0.4.1 (2026-09-14) vs upstream v0.5.0 (2026-09-23) with Server/API changes
- acceptance: every downloadable asset in `catalog.json` carries a per-tag/per-backend sha256; all `ensure_runtime_installed` call sites pass the pin; a tampered asset fails closed (unit test with a wrong pin proves the failure path); engine tag bumped to v0.5.0 only after llama-server flag compatibility is verified (smoke: server boots and answers `/health` under the fork's flag set)
- evidence: tests under `tests/hermes_cli/local_runtime/` (pattern: existing `test_install_cua_pin_contract.py`) green via `scripts/run_tests.sh`; catalog diff shows sha256 fields

### Port the upstream launchd JXA wrapper (stop osascript idle-CPU spin)
- id: `rm-030` | track: reliability | priority: 90.0 | status: candidate
- signals: fork `hermes_cli/gateway_launchd.py:216-236` still emits `/usr/bin/osascript -e 'do shell script …'`; upstream fix `8682d5791b` (2026-09-22, on upstream/main, absent from fork — ancestor-verified) plus issue #127651 measuring ~3.3–5% idle CPU per macOS launchd gateway (0.0% after fix)
- acceptance: `launchd_program_arguments` uses the JXA `$.system()` form; the Local-Network entitlement behavior from #71206 is preserved (existing entitlement test still green); upstream's added tests (`tests/hermes_cli/test_gateway_service.py`, +47 lines) ported alongside
- evidence: fork diff matches upstream `8682d5791b` semantics; targeted battery green; macOS lane marker sweep lists the wrapper test

### Void the phantom scan lists in rm-001/rm-002 derivations (dirty-scan hygiene)
- id: `rm-031` | track: reliability | priority: 88.0 | status: candidate
- signals: ROADMAP render b8a6730407 carried 19× `.worktrees/t_171b1032/**` and 20× `hermes_cli/web_dist/assets/react-vendor-*.js::L1` signals — both untracked (`git ls-files .worktrees` → 0; `git ls-files hermes_cli/web_dist` → 0); stripping the phantom prefix and re-verifying at HEAD shows 18 of rm-002's 19 real modules already have tests (only `acp_adapter/content.py` and `acp_adapter/__main__.py` do not)
- acceptance: signal derivation runs on a clean tree (or `git ls-files`-filtered): untracked directories (`.worktrees/`) and build output (`hermes_cli/web_dist/`) are excluded from signals and acceptance lists; re-render emits zero untracked paths
- evidence: `git ls-files`-filtered derivation output attached to the cycle; next render contains only tracked paths

### Add the two genuinely missing acp_adapter test files
- id: `rm-032` | track: reliability | priority: 85.0 | status: candidate
- signals: `tests/acp_adapter/` has no test importing `acp_adapter.content` or the `acp_adapter/__main__` entry shim (verified by grep over `tests/`); every sibling module (auth, commands, entry, events, permissions, provenance, server, session, tools) has a test file
- acceptance: `tests/acp_adapter/test_content.py` (or equivalent) covers content conversion invariants with at least one behavior-contract test; the `__main__` shim gets either a smoke test or a documented waiver (entry shims may be exercised by the packaging lane instead)
- evidence: new tests pass via `scripts/run_tests.sh tests/acp_adapter/`

### Silence the providers.<name>.enabled "unknown config keys" warning
- id: `rm-033` | track: customer-experience | priority: 80.0 | status: candidate
- signals: `_KNOWN_PROVIDER_KEYS` (`hermes_cli/config_providers.py:114-121`) lacks `"enabled"` while `is_provider_enabled` (`:601`) honors it, so self-written configs warn on every load (`:207`); upstream #127727 has the same RCA (PR imminent upstream)
- acceptance: `"enabled"` added to `_KNOWN_PROVIDER_KEYS`; a disabled provider still never reaches discovery (guard test); a self-written config with only `enabled` produces zero warnings (silence test); both tests proven red on base
- evidence: 2 invariant tests under `tests/hermes_cli/` green via `scripts/run_tests.sh`

### Scope the credential-pool unmatched-rotation stop (#127722)
- id: `rm-034` | track: reliability | priority: 80.0 | status: candidate
- signals: `_rotate_unmatched` guard (`agent/credential_pool.py:2193-2202`) declines rotation when exactly one entry of a multi-entry pool is available, falling back to `fallback_providers` even though the available entry is a different credential; upstream #127722 documents the same shape with RCA
- acceptance: the stop fires only when NO different credential exists; a 2-entry pool with 1 available rotates to it; a 1-entry pool still stops; a distinct "cannot rotate: no alternative credential" log line replaces the current ambiguous message
- evidence: pool-rotation tests (≥3 cases) green via `scripts/run_tests.sh`; or upstream's merged fix adopted with its tests

### Add local efficiency counters: prompt-cache breaks and wasted tokens
- id: `rm-035` | track: reliability | priority: 70.0 | status: candidate
- signals: fork has zero cache-break/wasted-token observability (greps for `wasted_tokens`/`cache_break` empty; only `agent/agent_init.py:582` OpenRouter header counter) although per-conversation prompt caching is the repo's #1 invariant; upstream telemetry v5 (`607dff390a`, 2026-09-27, absent from fork) implements exactly these local counters behind consent
- acceptance: per-session counters for prompt-cache breaks, wasted tokens, and tool-output truncation are recorded locally and surfaced through a `hermes` CLI command and/or dashboard card; NO outbound transmission (the counter module imports no HTTP client; grep-provable) — measurement half of upstream telemetry v5 only
- evidence: unit tests simulate a cache break and assert the counter; CLI/dashboard surface smoke-tested; `grep -rn "http" <new module>` shows no client

### Port the desktop idle-renderer performance batch
- id: `rm-036` | track: reliability | priority: 60.0 | status: candidate
- signals: upstream tracker #127647 (desktop idle resource burn) merged fixes `8ccb4c2cee` (scope background-throttling opt-out to live streaming), `4712721033` (pause decorative animations when unfocused), `76e0ca88` (order-independent selection guard), `d4725254` (best-effort lazy session-states import) — all on upstream/main and absent from the fork (ancestor-verified); the serve-CPU halves (`0caf219aaf`, `1eb5cd6124`, `56af2bdf7`) are already present
- acceptance: the four commits port in upstream-main order (do NOT port `3cad0f312b` — not on main); idle CPU/GPU of an unfocused window measurably drops (upstream tracker receipts cite numbers); desktop vitest lane green
- evidence: per-commit ancestry in the fork after landing; vitest + `tests/scripts/desktop_update/` green

### Split apps/desktop/electron/main.ts (18,907 lines, 110 IPC handlers)
- id: `rm-037` | track: reliability | priority: 55.0 | status: candidate
- signals: `wc -l apps/desktop/electron/main.ts` = 18,907 with 110 `ipcMain.handle` registrations; grew +516 lines since the prior assess tree `bcf55bbaed` (18,391); ~9.4× the repo's own ~2,000-line split signal (root AGENTS.md Code Shape Rules)
- acceptance: handlers extracted domain-by-domain into ≥4 modules with `main.ts` under 2,500 lines at the end of the first tranche; zero handler behavior change (characterization tests over the IPC contract first); desktop vitest lane green
- evidence: line-count before/after; vitest green; no orphaned handlers (registration count 110 → 110 across modules)

### Sync the plugin catalog with upstream
- id: `rm-038` | track: customer-experience | priority: 50.0 | status: candidate
- signals: `git diff HEAD upstream/main --stat -- plugin-catalog/` = 155 files, +3040/−171 (new plugins + pin refreshes) at upstream a042567296
- acceptance: catalog entries match upstream pins (SHA-pinned per policy); `plugin-validate` clean over the synced catalog; no self-updater entries (rule enforced in CI)
- evidence: catalog diff summary + validator output recorded in the cycle

### Add test coverage for 2 untested acp_adapter module(s) — amended from the phantom render
- id: `rm-002` | track: reliability | priority: 40.0 | status: candidate
- signals (amended 2026-09-29, attempt 353873407f4d46ab81de8d83165dc210): original render listed 20 paths under `.worktrees/t_171b1032/**` (untracked scratch tree — phantom); after prefix-stripping and re-verification at HEAD, only `reliability.no_tests:acp_adapter/content.py` and `reliability.no_tests:acp_adapter/__main__.py` remain untested (18/19 real modules already have tests)
- acceptance: both modules have a corresponding test file with at least one passing test (subsumed by `rm-032`; kept for render continuity)
- evidence: full suite green (python -m pytest -q) at HEAD; conductor validation digest validation:v1:<sha> recorded in the shipping PR

### Refactor 20 high-complexity function(s) — signals voided as untracked build output
- id: `rm-001` | track: reliability | priority: 35.0 | status: candidate
- signals (amended 2026-09-29, attempt 353873407f4d46ab81de8d83165dc210): all 20 original signals pointed at `hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1` — an untracked minified bundle (`git ls-files hermes_cli/web_dist` → 0); "decompose below the branch threshold" is unsatisfiable for vendored build output; superseded in practice by `rm-037` (real structural debt in tracked desktop sources)
- acceptance: re-derive complexity signals over tracked sources only (exclude `web_dist/`, `.worktrees/`); any resulting function list decomposed below the branch threshold with behavior locked by characterization tests
- evidence: ast-based branch-count check passes at HEAD over tracked paths (full suite green; conductor validation digest validation:v1:<sha> recorded in the shipping PR)

### Refresh stale top-level documentation
- id: `rm-003` | track: reliability | priority: 43.0 | status: candidate
- signals: reliability.stale_doc:README.md
- acceptance: Docs regenerated/updated; staleness detector reports 0 signals
- evidence: inference.stale_docs returns [] for the repo

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

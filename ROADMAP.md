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

### Extend sensitive-path hardening to desktop fs mutation IPC
- id: `rm-028` | track: reliability | priority: 97.0 | status: candidate
- signals: security.mutation_ipc_unfiltered:apps/desktop/electron/fs-ipc.ts::L173 (rename), ::L200 (writeText), ::L226 (trash) — `grep -n sensitive apps/desktop/electron/fs-ipc.ts` → 0 matches; read side enforces `rejectSensitiveFilePath` by default at apps/desktop/electron/hardening.ts::L501-L541 (calls :517/:533); writeText comment (:197) claims "allowed roots" that no code enforces
- acceptance: rename/writeText/trash reject sensitive paths by default via the same `rejectSensitiveFilePath` seam (opt-out flag parity with reads); rename/trash also pass `resolveRequestedPathForIpc`; the unsupported "allowed roots" comment is deleted or replaced by the real invariant; unit tests cover allow/deny/opt-out for all three handlers; full desktop test lane green
- evidence: assess attempt 5012779a finding F1 (/tmp/assess-5012779a/findings.md); grep receipts recorded in the shipping PR

### Retain unretained async cleanup tasks (deadline abandon + discord fatal-notify)
- id: `rm-029` | track: reliability | priority: 95.0 | status: candidate
- signals: agent/deadline.py::L266 `asyncio.ensure_future(_run_abandon_cleanup(...)).add_done_callback(...)` — done-callbacks live on the task, no strong ref held; plugins/platforms/discord/adapter.py::L1218 bare `asyncio.create_task(_notify())` on the fatal path; invariant seam gateway/run_shutdown.py::L1703-L1706 `_retain_background_task` (sibling pattern gateway/slash_commands.py::L810-L814)
- acceptance: both sites retained in a module-level set with discard-on-done mirroring `_retain_background_task`; no behavior change on the abandon/notify paths; targeted tests stay green
- evidence: assess attempt 5012779a findings F2/F3; prior class census (#15567 N3 18 sites, #15901 F6) confirmed these two sites are new

### Dependency wave 2026-10 — resolver-visible set
- id: `rm-030` | track: reliability | priority: 85.0 | status: candidate
- signals: pins behind PyPI latest as of 2026-10-03 (research 4b5b86cf §1), all ≥14d old so `exclude-newer = "14 days"` needs no exception: requests 2.33.0→2.34.2, croniter 6.0.0→6.2.4, starlette 1.3.1→1.7.0, uvicorn 0.41.0→0.54.0, agent-client-protocol 0.9.0→0.12.1, numpy 2.4.3→2.5.3, onnxruntime 1.27.0→1.30.0, sherpa-onnx 1.13.4→1.13.8, ruamel.yaml 0.18.17→0.19.1, prompt_toolkit 3.0.52→3.0.53, httpx2 2.13.0→2.13.1, ty 0.0.21→0.0.84, pytest-asyncio 1.3.0→1.4.0, debugpy 1.8.20→1.8.22
- acceptance: pins bumped, `uv lock` regenerated with zero new exclude-newer exceptions, full suite green on the new lock, OSV scan over exact pins reports no advisories
- evidence: PyPI JSON API receipts (2026-10-03) + lockfile diff in the shipping PR

### Exception-gated bumps + mcp 2.3.0 after quarantine expiry
- id: `rm-031` | track: reliability | priority: 82.0 | status: candidate
- signals: cryptography 50.0.0→50.0.2 (OpenSSL 4.0.3 wheels + abi3t wheels for free-threaded CPython 3.15+), fastapi 0.133.1→0.142.2, slack-sdk 3.44.1→3.45.0, google-api-python-client 2.194.0→2.201.0, ruff 0.15.10→0.16.10 — all released inside the 14-day window (cutoff 2026-09-19) so each needs a dated `[tool.uv]` exception line like the aiohttp/h2 precedent; mcp 2.2.0→2.3.0 (released 2026-10-02) is resolver-blocked until 2026-10-16
- acceptance: dated exception lines added then removed; mcp 2.3.0 bump includes an audit of our tool registrations for `x-mcp-header` annotations (now raising at registration) and a check that the empty-`_meta`/`params` omission passes our client paths; full suite green on each bump
- evidence: pyproject.toml [tool.uv] comment block; modelcontextprotocol/python-sdk v2.3.0 release body (2026-10-02)

### npm patch wave — electron 40.10.6, vite, react
- id: `rm-032` | track: reliability | priority: 78.0 | status: candidate
- signals: apps/desktop/package.json electron 40.10.2 vs 40-x-y dist-tag tip 40.10.6 (4 patch releases, Chromium security cadence); vite 8.2.0→8.3.2; react 19.2.7→19.3.0; typescript 6.0.3→7.0.2 tracked separately as a major
- acceptance: bumps land in package.json + lockfile, desktop build succeeds, vitest suite green
- evidence: npm dist-tags receipts (2026-10-03)

### Pre-book Python 3.15 CI lane before the 2026-10-07 final
- id: `rm-033` | track: reliability | priority: 74.0 | status: candidate
- signals: endoflife.date cadence (3.14.0 released 2025-10-07 → 3.15.0 final 2026-10-07, 4 days out); cryptography 50.0.2 already ships abi3t wheels for free-threaded CPython 3.15+
- acceptance: 3.15 CI lane added (allow-failure until final), pyproject upper-bound audit performed for 3.15, cryptography≥50.0.2 prerequisite landed (rm-031), suite green on 3.14 lanes
- evidence: endoflife.date API receipts (2026-10-03); pyca/cryptography CHANGELOG 50.0.2 entry

### Decide v2026.9.24 tag merge vs selective ports
- id: `rm-034` | track: reliability | priority: 70.0 | status: candidate
- signals: fork merge-base = v2026.9.21 (d337b736aa), fork does NOT contain v2026.9.24 (460 PRs / 4,828 files: per-profile multiplexer stop/start/restart + gateway.standalone, live dock, webhook mirroring 11fb429f49, hot-path perf, i18n); 91 files changed on both sides; pyproject/uv.lock conflicts certain; fork dep floors sit ahead of the tag
- acceptance: recorded decision with a merge-conflict triage (pyproject/uv.lock resolution strategy that preserves fork floors), a re-homing list for fork-settled classes (WSL link-open, locale-decode, waiter-leak), and either a green full suite at merged HEAD or a prioritized selective-port list
- evidence: research 4b5b86cf §3; upstream v0.21.5 release body; deea8546 campaign merge-window analysis

### ~/.hermes retention + snapshot service
- id: `rm-035` | track: reliability | priority: 66.0 | status: candidate
- signals: unbounded spill growth under ~/.hermes (pastes/, hook_outputs/, delegation summaries — cycle-1 assess F8) pairs directly with upstream user demand #12238 (27👍 auto-backup & versioning of ~/.hermes)
- acceptance: retention policy (config-gated defaults) + snapshot/backup CLI command; bounded growth proven with A→B→A E2E against two temp HERMES_HOMEs; user docs updated; no cache-invalidating mid-conversation behavior
- evidence: cycle-1 assess F8 receipts; GitHub issue reactions receipt (2026-10-03)

### SearXNG web-search provider
- id: `rm-036` | track: customer | priority: 48.0 | status: candidate
- signals: upstream demand #5941 (30👍, self-hosted/privacy search); existing web-search provider seam (firecrawl/exa/tavily/parallel-web extras via lazy_deps)
- acceptance: provider extra + parity in `hermes setup`/`hermes tools` UX; E2E against a local searxng instance (skippable marker when unavailable); no new core tool footprint (Footprint Ladder rung 3–4)
- evidence: GitHub issue receipt; pyproject extras inventory

### openai 3.x HTTPX2 migration lane (anthropic 1.x follow-up)
- id: `rm-037` | track: reliability | priority: 44.0 | status: candidate
- signals: openai 2.24.0→3.24.0 with 3.0.0 breaking change "HTTPX2 is now the default HTTP client" (2026-08-12, httpx2.md migration guide); fork already pins httpx2 2.13.x for MCP; anthropic 0.87.0→1.11.0 same shape
- acceptance: provider-lane migration following openai-python httpx2.md; classic httpx retained for unmigrated paths; provider test lanes green; anthropic 1.x handled as its own lane
- evidence: openai-python v3.0.0 release body; fork pyproject httpx/httpx2 pins

### Evaluate high-demand upstream feature requests
- id: `rm-038` | track: customer | priority: 30.0 | status: candidate
- signals: upstream open-issue demand 2026-10-03 — #25267 Claude Agent SDK OAuth provider (57👍, top ask), #18715 remote agent + local tool execution (37👍), #5257 ACP multi-agent orchestration (25👍; we ship the acp extra), #39691 headroom-ai compression (17👍)
- acceptance: per-item evaluation note (fit vs Footprint Ladder, plugin vs core, cost) recorded in ROADMAP.md or the dev guide before any implementation item is opened
- evidence: GitHub search receipts (reactions-+1-desc, 2026-10-03)

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

# hermes-agent — Roadmap

> Autonomously maintained by the roadmap sync (reliability-first). Items cite reproducible codebase signals; acceptance is proven by cited evidence.

**Vision**: A reliable, customer-friendly repository advanced by evidence-cited roadmap cycles owned by the autonomy loop

**Pillars**: reliability work outranks customer-experience work; every roadmap item cites reproducible codebase signals; acceptance is proven by cited evidence, never claimed

## Open items

### Add test coverage for 20 untested module(s)
- id: `rm-002` | track: reliability | priority: 100.0 | status: candidate
- signals: reliability.no_tests:.github/scripts/run-workspace-checks.mjs, reliability.no_tests:.worktrees/t_3143b8b5/.github/scripts/run-workspace-checks.mjs, reliability.no_tests:.worktrees/t_3143b8b5/acp_adapter/__main__.py, reliability.no_tests:.worktrees/t_3143b8b5/acp_adapter/auth.py, reliability.no_tests:.worktrees/t_3143b8b5/acp_adapter/commands.py (+15 more)
- acceptance: Every module in ['.github/scripts/run-workspace-checks.mjs', '.worktrees/t_3143b8b5/.github/scripts/run-workspace-checks.mjs', '.worktrees/t_3143b8b5/acp_adapter/__main__.py', '.worktrees/t_3143b8b5/acp_adapter/auth.py', '.worktrees/t_3143b8b5/acp_adapter/commands.py', '.worktrees/t_3143b8b5/acp_adapter/content.py', '.worktrees/t_3143b8b5/acp_adapter/edit_approval.py', '.worktrees/t_3143b8b5/acp_adapter/entry.py', '.worktrees/t_3143b8b5/acp_adapter/events.py', '.worktrees/t_3143b8b5/acp_adapter/model_catalog.py', '.worktrees/t_3143b8b5/acp_adapter/permissions.py', '.worktrees/t_3143b8b5/acp_adapter/provenance.py', '.worktrees/t_3143b8b5/acp_adapter/server.py', '.worktrees/t_3143b8b5/acp_adapter/session.py', '.worktrees/t_3143b8b5/acp_adapter/tools.py', '.worktrees/t_3143b8b5/agent/account_usage.py', '.worktrees/t_3143b8b5/agent/acp_openai_bridge.py', '.worktrees/t_3143b8b5/agent/activity_tracking.py', '.worktrees/t_3143b8b5/agent/agent_init.py', '.worktrees/t_3143b8b5/agent/agent_runtime_helpers.py'] has a corresponding test file with at least one passing test
- evidence: CI: pytest collects the new test files and they pass

### Refactor 20 high-complexity function(s)
- id: `rm-001` | track: reliability | priority: 90.0 | status: candidate
- signals: reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1, reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1, reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1, reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1, reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1 (+15 more)
- acceptance: Each flagged function is decomposed below the branch threshold with behavior locked by characterization tests
- evidence: ast-based branch-count check passes in CI

### Port the upstream SSRF-guard routing for remote-party URL fetches
- id: `rm-020` | track: reliability | priority: 88.0 | status: candidate
- acceptance: Hunk-level content diff of every file 3933fdf63b touches vs this tree; each raw-fetch site present here routes through tools/url_safety (or the ported equivalent); regression tests prove at least the model-supplied-image-ref and sitemap-<loc> sites refuse internal/metadata addresses (red on base, green after)
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Test the genuinely untested agent/ modules (supersedes rm-002's phantom list)
- id: `rm-015` | track: reliability | priority: 84.0 | status: candidate
- acceptance: Each of the 18 real agent/ modules + run-workspace-checks.mjs has a test file with ≥1 passing behavior-contract test (no change-detectors); rm-002 retired as superseded once this lands
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Harden the roadmap sync against dirty scan environments
- id: `rm-016` | track: reliability | priority: 82.0 | status: candidate
- acceptance: Sync filters untracked/ignored paths and build output, dedupes signals, cites only in-repo-verifiable evidence, and is idempotent (re-running on a clean checkout produces no duplicate landing); ROADMAP.md regenerated from a clean checkout with rm-002's list corrected
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Port the upstream security-fix family (lifecycle guard, api_server sanitize, keychain, oauth)
- id: `rm-021` | track: reliability | priority: 80.0 | status: candidate
- acceptance: Each fix ported by content with a symptom-proving regression test (decoy Windows gateway cmdline NOT lifecycle-killed; runtime metadata shape asserted; keychain mirror round-trip against a stub `security` tool; oauth error text carries a redacted excerpt, never the raw token) and a per-commit port-decision note (ported / already-present / N-A with reason)
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Make Windows venv holder detection token-exact
- id: `rm-018` | track: reliability | priority: 78.0 | status: candidate
- acceptance: Holder classification uses full-token/path-exact matching (the canonical matcher pattern); a decoy process with the venv path in its arguments is NOT classified as a holder; windows live lane (wine2e) probe covers the case
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Guard ROADMAP.md against sync-channel truncation (extends rm-016)
- id: `rm-023` | track: reliability | priority: 74.0 | status: candidate
- acceptance: The dirty canonical working file restored to committed HEAD state (git checkout -- ROADMAP.md) or consciously superseded by a verified regenerate; the landing pipeline refuses/flags any ROADMAP.md update that deletes non-empty sections present in HEAD (additions-only guard); a dry-run of the sync against committed HEAD shows no truncation
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Port the upstream compression/loop hardening family
- id: `rm-012` | track: reliability | priority: 72.0 | status: candidate
- acceptance: Hunk-level content diff confirms which fixes are missing; each missing fix ported with a regression test proving the symptom on base (unexplained server context rejection not mislabeled; review budget bounded; duplicate task sections collapsed)
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Remove the dead _read_env_var and its dead-behavior test
- id: `rm-017` | track: reliability | priority: 66.0 | status: candidate
- acceptance: Either deleted with its test, or repointed to hermes_constants.get_hermes_home() with a real production caller; no hardcoded ~/.hermes path remains in the module
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Upgrade provider/protocol SDKs behind provider lanes
- id: `rm-013` | track: reliability | priority: 64.0 | status: candidate
- acceptance: Each SDK bumped with repo upper bounds and its provider lane green (anthropic, openai-compatible, mcp client/server, acp adapter round-trip); breaking-change migration notes in the PR
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Refresh CI supply-chain tooling (uv pylock, osv-scanner 2.6.0)
- id: `rm-014` | track: reliability | priority: 56.0 | status: candidate
- acceptance: Runner uv ≥0.12.11; uv-lockfile-check lane exports and verifies a pylock.toml alongside uv.lock; osv-scanner pinned to 2.6.0 with digest verification from release assets; both lanes green
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Teach SHA pinning in the plugin-validate action snippet
- id: `rm-019` | track: reliability | priority: 52.0 | status: candidate
- acceptance: Snippet shows a SHA-pinned reference (+ # vN comment) for the action; rendered docs regenerated if they embed the snippet
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Triage the pristine-baseline full-suite failure and flake ledger
- id: `rm-027` | track: reliability | priority: 52.0 | status: candidate
- acceptance: each of the 16 pre-existing failures root-caused (real defect vs env/host mismatch vs timing) and fixed or explicitly accept-and-tracked; hermes_state timeout resolved or reclassified; the flake ledger recorded with solo-vs-load classification per file
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Sync the plugin catalog from upstream (127 add-only entries)
- id: `rm-004` | track: reliability | priority: 48.0 | status: candidate
- acceptance: Every upstream plugin-catalog YAML as of 1baae3132a exists verbatim in plugin-catalog/ (count parity 137=137, our 10 divergent entries preserved); plugin-catalog CI validation green; a catalog-listing smoke test shows a newly synced entry
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Add session_search time bounds and session exclusion
- id: `rm-005` | track: reliability | priority: 44.0 | status: candidate
- acceptance: Tool schema carries after/before/exclude_session_ids; FTS recall respects bounds (inclusive semantics pinned by tests) and excludes listed sessions; date-scoped recall proven by an E2E test against a temp session DB
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Refresh stale top-level documentation
- id: `rm-003` | track: reliability | priority: 43.0 | status: candidate
- signals: reliability.stale_doc:README.md
- acceptance: Docs regenerated/updated; staleness detector reports 0 signals
- evidence: inference.stale_docs returns [] for the repo

### Remove the dead as_exclusive_end parameter from _parse_iso_bound
- id: `rm-024` | track: reliability | priority: 40.0 | status: candidate
- acceptance: Parameter removed with the caller updated (or made load-bearing with a test); the docstring describes the actual date-only→midnight-UTC conversion and states where exclusivity is enforced; session_search + FTS consumer suites green
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Port skills.auto_load from upstream
- id: `rm-006` | track: reliability | priority: 36.0 | status: candidate
- acceptance: config.skills.auto_load (default off) pins listed skills into new sessions' prompts; with the config unchanged the system prompt stays byte-stable across turns (prompt-caching invariant); enabling is documented as next-session-effective per the cache-aware slash-command convention
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Auto-install catalog-listed memory providers named in config
- id: `rm-009` | track: reliability | priority: 34.0 | status: candidate
- acceptance: A config naming a catalog-listed but unimportable memory provider resolves via plugin-catalog, installs, and passes doctor validation; failure path leaves a clear actionable message
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Document deliver:api_server in the cron user docs
- id: `rm-025` | track: reliability | priority: 30.0 | status: candidate
- acceptance: The cron feature/guide docs list api_server among deliver targets with the transcript-delivery behavior and the no-credential-needed note; docs build green
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Add the Blender MCP bridge and backend-local app discovery
- id: `rm-010` | track: reliability | priority: 26.0 | status: candidate
- acceptance: Blender bridge installable from the catalog and functional against a stub MCP server; app discovery is opt-in and does not probe when disabled
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Parameterize the native vision embed budget
- id: `rm-007` | track: reliability | priority: 24.0 | status: candidate
- acceptance: vision.embed_target_bytes config (default = current behavior) replaces the hardcoded budget; override proven by test
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Refresh video generation model families
- id: `rm-008` | track: reliability | priority: 22.0 | status: candidate
- acceptance: New families listed with correct tier/pricing/audio metadata and reachable via the video_gen tool; no existing family removed
- evidence: campaign-recorded in hermes-agent ROADMAP.md

### Decide gateway.multiplex_profiles default (upstream flipped to on)
- id: `rm-011` | track: reliability | priority: 20.0 | status: candidate
- acceptance: Decision recorded (keep-off or flip) with rationale; if flipped, a boot-time serve guard prevents conflicting multiplex serving and migration is documented
- evidence: campaign-recorded in hermes-agent ROADMAP.md

<!-- managed by hermes-roadmap render; do not edit by hand -->

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
- rider (2026-10-06, run 982bba542fb5 roadmap, assess f80e1dac): signal list is still phantom-laden — 19 of 20 entries are vendored `hermes_cli/web_dist/assets/` bundles or `.worktrees/t_171b1032/` scan residue (rm-015 already superseded it once for exactly this); re-derive the untested-module census from a clean checkout at implement time before spending the priority-100 slot

### Refactor 20 high-complexity function(s)
- id: `rm-001` | track: reliability | priority: 90.0 | status: candidate
- signals: reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1, reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1, reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1, reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1, reliability.complexity_hot:hermes_cli/web_dist/assets/react-vendor-BoVnYuL4.js::L1 (+15 more)
- acceptance: Each flagged function is decomposed below the branch threshold with behavior locked by characterization tests
- evidence: ast-based branch-count check passes at HEAD (full suite green; conductor validation digest validation:v1:<sha> recorded in the shipping PR)
- rider (2026-10-06, run 982bba542fb5 roadmap, assess f80e1dac): all 20 complexity signals point at the vendored `react-vendor-BoVnYuL4.js` bundle (built output, not source) — re-derive the hot-function list from source .py/.ts at implement time; the two god-FILES split out below as rm-095/rm-096 are file-level decompositions, outside this item's function-level scope

### Refresh stale top-level documentation
- id: `rm-003` | track: reliability | priority: 43.0 | status: candidate
- signals: reliability.stale_doc:README.md
- acceptance: Docs regenerated/updated; staleness detector reports 0 signals
- evidence: inference.stale_docs returns [] for the repo

<!-- cycle-1 extension (2026-10-06, conductor run 982bba542fb54911ac8794d9d3f74437 roadmap f50b0e76, from assess f80e1dac @ 7403d41bf4 == origin/main + research fca9f464): 17 items minted rm-088..rm-104. ID basis (census re-derived first-hand 2026-10-06): in-file max rm-027; all-lineage committed ceiling rm-087 (conductor-salvage 93443b93c28, run 4938049a, plus 09-28 terminal-estate records); one unlanded dead-lineage worktree claim rm-028..rm-038 (run-4f8c2414429a, uncommitted diff, lineage idle since 2026-09-29) — mints start at rm-088, collision-free under every convention. Dedupe: rm-089 subsumes the unlanded rm-029 task-retention claim (narrower: 2 sites vs the 29-site class); rm-090/rm-092 are selective ports, consistent with the unlanded rm-034 merge-vs-selective-ports decision claim; research-rejected candidates (already in the fork via the v0.21.5 release line: cua-driver, NVIDIA skills-hub tap, per-channel overrides, provider_catalog(), ContextEngine ABC, Browser Use cloud integration, fallback-model routing, skills.external_dirs, /model live fetch) are NOT re-proposed. -->

### Deny dashboard read-side access to vault and browser-profile
- id: `rm-088` | track: reliability | priority: 96.0 | status: candidate
- signals: hermes_cli/web_routers/files.py:78 `_SENSITIVE_MANAGED_DIR_NAMES = frozenset({"mcp-tokens", "pairing"})` — omits `vault`/`browser-profile` while the write/tool sides deny them (file_safety.py:246/:251), so managed-file list/read/download serves vault.key + vault.json.enc and browser cookies; vault at-rest perms are solid (vault_store.py 0o700/0o600/O_EXCL), making the router the sole exposure (assess SEC-1 HIGH, anchor re-verified 2026-10-06)
- acceptance: list/read/download under `vault/` and `browser-profile/` denied by the same frozenset (or equivalent guard) with write/tool sides unchanged; E2E against a temp HERMES_HOME proves a prepared vault key/blob and a browser-profile cookie file are unreadable via the router while a benign managed file still reads; suite green
- evidence: assess f80e1dac SEC-1 (sed anchor files.py:78); grep receipts in the shipping PR

### Shared background-task retention for the unretained-task class (29 sites)
- id: `rm-089` | track: reliability | priority: 94.0 | status: candidate
- signals: AST census 2026-10-06 (/tmp/assess_census.py, assess REL-5): 29 bare `create_task`/`ensure_future` expression-statement sites across agent/ gateway/ tools/ hermes_cli/ cron/ tui_gateway/ acp_adapter/ plugins/; headline anchors — gateway/platforms/weixin.py:829 dispatches INBOUND user messages unretained (GC'd task = silent message loss, next to the "dispatch before persisting" comment :826-827); gateway/platforms/base.py:2703-2714 `_schedule_ephemeral_delete` runs the self-deleting (privacy) message deletion detached; gateway/run_turn.py:1676 process watcher; gateway/platforms/api_server.py:164 browser-control WS frame send; repo bar already exists — `_retain_background_task` (gateway/run_adapters.py:467,618,799) and `_background_tasks`+done_callback (bluebubbles.py:605-607)
- acceptance: a shared retain helper adopted at every census site except a documented shutdown-path allowlist (gateway/run.py:5336); re-running the AST census reports 0 unretained sites outside the allowlist; a forced-GC regression test proves an inbound weixin message dispatched via create_task survives collection pressure; suite green
- evidence: assess f80e1dac REL-5 (full 29-site list in the findings artifact); subsumes the unlanded rm-029 claim (deadline abandon + discord fatal-notify, 2 sites) — fold at integrate

### Adopt upstream truststore-based OS-native TLS trust
- id: `rm-090` | track: reliability | priority: 84.0 | status: candidate
- signals: fork agent/ssl_verify.py = 56 lines with 0 truststore references and no pyproject pin (grep 2026-10-06); upstream same file = 155 lines / 14 truststore refs with `install_truststore()` patching ssl.SSLContext process-wide (httpx/requests/aiohttp/urllib all inherit OS trust) and pyproject `truststore==0.10.4` (rationale: corporate MITM root via MDM, internal CA, NixOS); read upstream follow-up f69d5777c6 (explicit-bundle contexts without importing truststore) before porting
- acceptance: truststore pinned per the dependency-pinning policy (>=floor,<next_major), agent/ssl_verify.py ports the process-wide install semantics, per-provider `ssl_ca_cert` remains the explicit override; E2E with a temp HERMES_HOME + custom CA in the OS trust store connects with zero config; suite green
- evidence: research fca9f464 candidate 1 (absence-verified against the fork tree 2026-10-06); upstream pyproject/ssl_verify receipts in the research artifact

### Ship the default browser engine (browser-harness pin + lazy-install seam)
- id: `rm-091` | track: reliability | priority: 80.0 | status: candidate
- signals: tools/browser_use_cli.py:51 `from browser_harness import _ipc` inside the daemon preamble with `except Exception: _dpid = "0"` fallback; tools/browser_tool.py:105-107 ImportError fallback to non-CLI mode; browser-harness declared NOWHERE in the fork — pyproject/uv.lock/tools/lazy_deps.py grep = 0 (lazy_deps carries no browser entries at all); upstream pins `browser-harness==0.1.13` in MAIN dependencies ("every install, Desktop bundle included, ships it"; commit 27062c3474) — the fork's default browser path silently degrades in lean installs
- acceptance: pin + lazy-install seam so browser_exec's default engine is actually shipped; fresh-install E2E (temp HERMES_HOME, browser_harness absent) reaches the CLI engine instead of the silent fallback; suite green
- evidence: research fca9f464 candidate 2 (absence-verified 2026-10-06)

### Port the managed-runtime no-user-fallback fix (upstream b63c138d78)
- id: `rm-092` | track: reliability | priority: 74.0 | status: candidate
- signals: upstream commit b63c138d78 "fix: Hermes never falls back to the user's node/npm/npx/uv" — the same doctrine the fork's AGENTS.md and tests/test_managed_runtime_resolution.py already enforce (resolver allowlist regime)
- acceptance: cherry-pick or equivalent port lands with contributor attribution preserved; every node/npm/npx/uv resolution path refuses user-installed binaries per doctrine; managed-runtime resolution tests green; no new bare shutil.which outside hermes_platform/resolver (allowlist audit clean)
- evidence: research fca9f464 candidate 5 (discipline fix independent of the PM subsystem)

### Purge event-loop-blocking sync IO in gateway/web media paths
- id: `rm-093` | track: reliability | priority: 72.0 | status: candidate
- signals: gateway/platforms/weixin.py:1134 `Path(path).read_bytes()` on arbitrary-size outbound attachments (video-sized reads block the whole gateway loop); whatsapp_cloud.py:661 `write_bytes(blob_resp.content)` plus sync open/read :509-513; hermes_cli/web_routers/files.py:597-599 `shutil.rmtree(target)` inside `async def delete_managed_file` (blocks the shared web loop); async primitives exist and are used by neighbors (base.py:1483 `cache_document_from_bytes_async`, base.py:1549 `cache_media_bytes_async`) — these sites bypass them
- acceptance: the named sites route through the async cache helpers or `to_thread`; grep/AST over the flagged functions shows no read_bytes/write_bytes/rmtree executing on the loop; a large-attachment send E2E does not stall concurrent gateway turns; suite green
- evidence: assess f80e1dac REL-6 + carried REL-3/PERF-1, anchors re-verified 2026-10-06

### Harden curator rollback tar extraction (symlink pivot)
- id: `rm-094` | track: reliability | priority: 70.0 | status: candidate
- signals: agent/curator_backup.py:426-434 — pre-validation loop rejects only absolute paths and `..`; `extractall(filter="data")` falls back to UNFILTERED `extractall` on TypeError (interpreters 3.11.0–3.11.3, inside requires-python >=3.11,<3.14); a clean-named SYMLINK member plus `name/...` file members writes through the symlink outside `skills/`; the repo's own bar `_extract_zip_safely` (hermes_cli/update_cmd_zip.py:233-246) rejects symlink members outright
- acceptance: the tar path mirrors the zip bar — symlink members rejected, and the TypeError fallback raises instead of extracting unfiltered; fixture test with a poisoned snapshot tar (symlink pivot) proves refusal while a healthy snapshot still restores; suite green
- evidence: assess f80e1dac SEC-6 (low — requires a poisoned locally-produced snapshot; snapshot tars are self-generated)

### Split agent/auxiliary_client.py (8,193 lines) into topical siblings
- id: `rm-095` | track: reliability | priority: 68.0 | status: candidate
- signals: wc -l = 8,193 (2026-10-06) vs the ~2,000-line doctrine bar (AGENTS.md "don't recreate god files"); 9 auxiliary_* siblings already exist for the facade+siblings layout, so the decomposition seam is established
- acceptance: file lands under the doctrine bar as facade + topic siblings along the existing `auxiliary_<topic>` convention; behavior locked by the existing suite; zero compat-pointer usage (scripts/check_compat_pointers.py clean); evals/codebase_navigability static_metrics before/after recorded in the shipping PR
- evidence: assess f80e1dac MAINT-1 (wc -l receipt)

### Split plugins/platforms/discord/adapter.py (7,384 lines)
- id: `rm-096` | track: reliability | priority: 66.0 | status: candidate
- signals: wc -l = 7,384 (2026-10-06); `_define_discord_view_classes` is a 565-line function (prior AST census, still live)
- acceptance: adapter decomposed under the doctrine bar with the 565-line function split; the plugin keeps working strictly within the plugin ABCs (no core special-casing); suite + discord adapter lanes green
- evidence: assess f80e1dac MAINT-2 (wc -l receipt)

### Web-surface security hygiene micro-batch
- id: `rm-097` | track: reliability | priority: 64.0 | status: candidate
- signals: gateway/platforms/bluebubbles.py:565 `if self._webhook_token(request) != self.password:` — non-constant-time compare (the pattern exists at web_server.py:416 `hmac.compare_digest`); hermes_cli/web_git.py:333 `[["rev-parse", ref or "HEAD"]]` — dashboard-supplied ref with no `--` separator (option injection); hermes_cli/dashboard_auth/public_paths.py:20 `/api/model/info` unauthenticated (exposure disposition unrecorded)
- acceptance: webhook token compare constant-time; rev-parse guarded (ref allowlist or `--` plus validation); `/api/model/info` disposition recorded — gated, or documented-intentional with a test pinning it; one targeted test per site; suite green
- evidence: assess f80e1dac SEC-3/SEC-4/SEC-5, anchors re-verified 2026-10-06

### Verify managed-Node archive integrity before extract
- id: `rm-098` | track: reliability | priority: 60.0 | status: candidate
- signals: hermes_constants.py:629 `archive.extractall(extract_dir)` with 0 SHASUMS/sha256 references anywhere in the file (grep 2026-10-06); the managed-Node download path for Windows
- acceptance: download verified against a pinned digest (upstream SHASUMS or an embedded sha256) before extraction; tampered-archive fixture test refuses extraction; suite green
- evidence: assess f80e1dac SEC-2 (carried, re-anchored this cycle)

### Port upstream layered i18n language packs
- id: `rm-099` | track: customer | priority: 58.0 | status: candidate
- signals: upstream 9bcbe7b5df (2026-09-28, #126296) adds agent/i18n_layers.py (283 lines) + agent/i18n_languages.py (74) and rewrites agent/i18n.py + display/turn-explainers/status across 60+ files; fork has basic agent/i18n.py (`t()` at cli_session_mixin.py:298, slash_exec.py:106) with both layer files verified ABSENT 2026-10-06
- acceptance: layered pack resolution ports (core/Desktop/TUI layers); existing `t()` call sites keep working; a non-English pack E2E renders CLI+TUI strings; no mid-conversation system-prompt mutation (cache-safe per the invariant); suite green
- evidence: research fca9f464 candidate 3 (absence-verified 2026-10-06)

### Adopt dual-Python (3.11/3.14) dependency tracks at the next upstream sync
- id: `rm-100` | track: reliability | priority: 56.0 | status: candidate
- signals: upstream pyproject restructures every core dep with `python_version >= '3.14'` markers (openai, certifi, httpx, pydantic 2.13.4 vs fork 2.13.5, cryptography 50.0.1 vs fork 50.0.0, fastapi, uvicorn, psutil, websockets); upstream requires-python >=3.11,<3.15 — trunk is dual-track, fork is single-track 3.11 (read 2026-10-06); drift compounds each release
- acceptance: at the next adoption sync the marker structure lands together with the cryptography 50.0.0→50.0.1 patch; `uv lock` resolves for both tracks; CI lanes for both Pythons green
- evidence: research fca9f464 candidate 6

### Bound platform-adapter resource growth
- id: `rm-101` | track: reliability | priority: 54.0 | status: candidate
- signals: gateway/platforms/bluebubbles.py:482-483 `data = resp.content` — uncapped attachment download (Signal caps 100 MB at signal.py:46); gateway/platforms/signal.py:218-220 `_recipient_uuid_by_number`/`_recipient_number_by_uuid` unbounded dicts
- acceptance: bluebubbles download bounded by the shared media cap; recipient maps bounded (LRU or persisted) with the UUID-upgrade send path intact; long-session E2E shows flat map growth; suite green
- evidence: assess f80e1dac REL-1/REL-4 (carried, re-anchored this cycle)

### Delete the dead first _print_external_login_notice definition
- id: `rm-102` | track: reliability | priority: 52.0 | status: candidate
- signals: hermes_cli/auth_commands.py:546-555 def#1 swallows `_print_oauth_heal_notices()` (:553), references undefined `provider_filter` (:554, NameError), and calls ITSELF (:555, infinite recursion if ever reached); def#2 (:558-562) cleanly shadows it; AST duplicate-def proof 2026-10-06
- acceptance: a single def remains; the auth-list tail calls `_print_oauth_heal_notices()` so heal notices actually surface; duplicate-def AST check clean; targeted auth tests green
- evidence: assess f80e1dac COR-1 enrichment (self-recursion added this cycle)

### Android/Termux platform support
- id: `rm-103` | track: customer | priority: 40.0 | status: candidate
- signals: upstream pyproject carries `psutil==7.2.2; sys_platform != 'android'` plus source pin `psutil @ git+…380bd2b…; sys_platform == 'android'` ("Android Python 3.13+ needs upstream #2891") and an android-emulator plugin (a0719b0799); fork pyproject has no android dependency markers (the 5 case-sensitive `android` hits are the PEP 738 kernel-release comment guard, not markers) and hermes_platform carries no android host facts
- acceptance: psutil dual-pin + hermes_platform host facts (Termux/android detection, no env-var input per the machine-facts rule); a Termux install E2E or a hardware-lane marker per the host-OS testing rule (never sys.platform patching); no bare platform sniffing outside hermes_platform
- evidence: research fca9f464 candidate 4

### Track (evaluate) upstream `pm` managed native-engine package manager
- id: `rm-104` | track: customer | priority: 30.0 | status: candidate
- signals: upstream `pm` subcommand versions native engines (llama.cpp pin bumps 7db063c59e/54e2a59bbc/361963828d, sudo-gated repair 4cf2ea805f, CI bundles 93c9360a8d); fork has no pm subcommand (grep hermes_cli/main.py = 0, 2026-10-06) — engines ride lazy_deps/managed-node
- acceptance: an evaluation note recorded (fit vs the Footprint Ladder — likely CLI command + skill rung; port size; whether fleet demand exists) BEFORE any implementation item opens
- evidence: research fca9f464 candidate 5

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

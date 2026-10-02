# Absorption Canvas — upstream v0.21.4 → v0.21.5 line (fork c4da06121c)

- artifact_contract: absorption-canvas/v1
- artifact_readiness: ledger (living doc — re-verify SHAs before each wave lands)
- execution: docs-only (this file); code landed in the wave-0 batch it records
- risk: low (no prod surface modified by this doc)
- date: 2026-10-02
- provenance: run 782825532f81 (repository-maintenance f757e85c, cycle 1), batch "Absorption wave 0"
  (stewardship 55f89a36; prioritize a61b8252; research 8c0456373e)

## 1. Pins and windows (re-verified live 2026-10-02)

| Ref | Meaning | Value |
|---|---|---|
| merge-base | v0.21.4 | `d337b736aa` (2026-09-21) |
| v0.21.5 release tag | `v2026.9.24` | `f97608f178` (2026-09-24) |
| research pin | rc.33 canary line | `f848940560` (2026-09-30 20:01 -0500) |
| fork HEAD | this repo | `c4da06121c` (17 local commits over merge-base) |

Window taxonomy — the "v0.21.5 absorption" umbrella is TWO sub-windows:

- **W1 `d337b736aa..f97608f178`** (the released v0.21.5): **1,638 commits**,
  4,828 files, +164,132/−149,440.
- **W2 `v2026.9.24..f848940560`** (canary/rc line, v0.21.6 in flight): **4,988 commits**.
  Every security SHA the wave-0 batch ports (2026-09-29/30 fixes) lives here, NOT in W1 —
  a plain "absorb the release tag" strategy would miss all of them. Re-pin W2's tip per wave;
  upstream moves hourly.

## 2. Census of W1 (commit-classification; scratch script `canvas-census.py`, /tmp only)

By type: fix 755 · test 298 · feat 121 · chore 114 · refactor 77 · docs 48 · fmt 37 · perf 35 ·
catalog 30 · ci 11. By scope (top): desktop 293 · bot-screen 99 · gateway 95 · catalog+plugin-catalog 108 ·
agent 45 · plugins 43 · config 29 · skills 28 · update 26 · cli 24 · kanban 19 · memory 17 ·
dashboard 16. By theme: desktop/electron 383 · gateway/platforms 180 · agent/memory 85 ·
ci/release 74 · **security/secrets 60** · skills/guard 55 · mcp/tools 54 · media/rendering 18.

Read: W1 is dominated by the desktop/bot-screen feature surface (research C7/C8) and by tests.
The security-critical remainder is small and nameable — that is why wave 0 ports fixes
individually instead of merging the line.

## 3. Wave 0 — LANDED in this batch (this turn; uncommitted worktree state is the deliverable)

Ports are semantic, not textual (6,626-commit drift makes cherry-picks conflict). All five
upstream commits sit in W2 and predate f848940560 (rc.33) except where noted.

| # | Upstream | Fork surface landed | Adaptation notes | Tests |
|---|---|---|---|---|
| B1 | `9c5da5a1c7` secret-source env revocation | `agent/secret_sources/registry.py` (`enabled_source_names`), `hermes_cli/env_loader.py` (`_SECRET_SOURCE_WRITES_BY_HOME`, `_record_secret_source_write`/`_revoke_removed_secret_source_values` wired into `_apply_external_secret_sources` + reset), `hermes_cli/plugins.py` (reconcile-on-unload: `_plugin_secret_sources_reconciled` marker; 1→0 disable now runs the refresh instead of early-returning) | our `env_loader.py` is 244 lines vs upstream ~730 — kept our snapshot model, added only the writes-ledger + revoke | `tests/hermes_cli/test_secret_source_bootstrap.py::test_removing_the_last_plugin_source_revokes_its_process_env_value` (revoked + other-owner-kept arms, A→B→A sibling home) — 10/10 file green |
| B2 | `0f24f8b8eb` skills-guard bare-`~` + inline-shell DSL + install-verdict propagation | `tools/skills_guard.py` + `hermes_cli/skills_hub.py` (landed pre-reap by attempt c7d7df84, verified this turn); `tui_gateway/methods_tools.py::_skills_install` 5031 error envelope | scan cache key already embedded `SCANNER_VERSION`; only verdict plumbing needed | +5 guard tests (`TestScanSkillCached` rescan-after-version-bump, bare-`~`, inline-shell) and new `tests/tui_gateway/test_skills_manage_install.py` (3) — 62/62 + 3/3 green |
| B3 | `0590ab25fe` zombie-aware stale-marker self-heal | `hermes_cli/update_lock.py::read_live_update` + `gateway/status.py::_pid_exists` (zombie-aware) + reader family `main_install_repair.py:122,189,204`, `update_cmd.py:405`, `update_cmd_windows.py:1414`, `update_cmd_deps.py:732`, `update_handoff.py:114`, `apps/desktop/electron/update-marker.ts` (landed pre-reap by c7d7df84, verified) | readers consult the shared liveness probe; JS side self-heals identically | `tests/hermes_cli/test_update_lock.py` + `test_early_recovery.py` 46/46; `electron/update-marker.test.ts` 21/21 (vitest) |
| B4 | `7327624d35` MEDIA-tag degenerate-path rejection | **CORRECTED SURFACE**: stewardship named `electron/media-protocol.ts`/`media-range.ts`, but the real fix is `apps/desktop/src/lib/chat-messages/parts.ts` (capture grammar `_MEDIA_PATH_BARE`, `isPlausibleMediaPath`, `splitTrailingPunctuation`) + `apps/desktop/src/lib/media.ts` (`pathToLocalFileUrl` %/#/? structural escaping). The protocol/range files are the *renderer* side and were already correct. | our fork's grammar pre-state was simpler (`\S+` branch, no bare-quoted handling); post-state byte-matches upstream's function bodies modulo the pre-existing `\n`-style escapes | new `parts.capture.test.ts` (5) + `media.remote.test.ts` additions (10) — 27/27 green incl. pre-existing `parts.test.ts` |
| B5 | `60800e87ca` Helper entitlements | `hermes_cli/main_desktop.py:839` comment + regression test only | **pre-verified no-op**: both plists already carry allow-jit/allow-unsigned-executable-memory/disable-library-validation; upstream's expression is semantically identical to ours — ported the comment + the missing test contract rather than dropping (stewardship pre-authorized drop; test-only carry is within "trim-only" bounds and protects the invariant) | `tests/hermes_cli/test_gui_command.py::test_desktop_macos_local_codesign_helper_apps_keep_jit_entitlements` — file 229/229 green |

Rider (rm-067 urlopen slice only): `scripts/ci/live_comment.py` (3 sites + doc'd 60s artifact
download), `publish_e2e_evidence.py` (2), `timings_report.py` (1) — all 7 `urlopen(` calls in
the three files now carry `timeout=` (`API_TIMEOUT_SECONDS = 30`, cron/monitor.py pattern).
`py_compile` clean. Census correction: live_comment.py:404 already had `timeout=60` at dispatch
time; the seven-site list from assess F3 overcounted by one (the fix covers every remaining site).

## 4. In-scope / out-of-scope ledger (reasons recorded)

**In scope (landed):** the five W2 security/robustness commits above; the urlopen rider.
Selection authority: prioritize a61b8252 (content-bound, not id-bound — see §6).

**Out of scope, with reasons:**

| Excluded | Why deferred |
|---|---|
| W1 bulk merge (desktop 293 / bot-screen 99 scope commits) | feature surface, not security; rides rm-065 (Bot Desktop suite decision), rm-070+ (connector catalog) — evaluate per footprint ladder, not absorb wholesale |
| cron no_agent scope overlay trio `136135e653`/`84e2ea9f8b`/`71303c7082` (W2, 2026-09-29) | named by research C1 but never selected by prioritize; overlaps campaign 3cf378a2's cron surfaces (rm-049..057) — first candidate of wave 1 (§5) |
| `df126f6a05` (research C1's sixth SHA) | same: unselected remainder → wave 1 triage |
| api_server memory-session family | rm-060, next-cycle anchor (sequencing override at prioritize; zero file overlap with wave 0) |
| telemetry/observability ride-alongs | parked behind rm-037 consent gate |
| rm-067 non-urlopen classes (timing asserts, `process_identity.py:47` dead import, elif ladders) | separate sweep, itemized in rm-067/rm-072 |
| secret-scope children + MCP owner scope | campaign a40d326ab (TAKEN); change-unit disjointness |
| kanban min-age gate (canonical rm-058) | id-drift casualty; never selected (§6) |

## 5. Wave-split of the remaining absorption items (dependency order)

- **Wave 1 — security remainder, W2 tip re-pinned:** cron no_agent overlay trio + `df126f6a05`
  (verify each still applies semantically at the new pin; the trio shares
  `build_subprocess_env` surfaces so it lands as ONE unit with a single E2E leg). Cheap, P1.
- **Wave 2 — rm-062 machine-facts doctrine** (`hermes_platform/` module): unlocks
  `tools/mcp_liveness.py` (imports `hermes_platform.*`) and removes the
  `web_routers/profiles.py:827` event-loop `which` loop (shared surface with rm-063). Do BEFORE
  rm-063 so the router fix lands against the doctrine, not as another ad-hoc read.
- **Wave 3 — rm-063 web-router blocking I/O** (`to_thread` census; upstream `files.py` has 23 vs
  our 2): mechanical, wide; runs after rm-062 to avoid double-touching `profiles.py`.
- **Wave 4 — rm-059 host-faking → OS-marked tests** (20 `sys.platform` fake sites): test-only,
  can interleave anywhere after wave 2 (its `test_linux_sandbox_fixup.py` arm touches sandbox
  code the doctrine rewrite revises).
- **Wave 5 — rm-060 api_server memory-session continuity**: largest port (#120116 family);
  next-cycle anchor per prioritize sequencing.
- **Wave 6 — rm-065 Bot Desktop suite decision** (adopt/defer/decline against the footprint
  ladder) and **rm-066 platform-adapter lifecycle hygiene** (wecom idle eviction + whatsapp dead
  queue; P4, zero upstream dependency — fork-local).

## 6. ROADMAP id drift (recorded for the next render)

The prioritize artifact's "rm-058" = THIS canvas (the v0.21.5 absorption item authored by this
run's roadmap phase). The re-rendered canonical ROADMAP.md:127 `rm-058` is the **kanban
dispatch min-age gate** (a re-added old item). The canvas item currently has NO id. The next
roadmap render must re-mint the canvas id and must not treat wave-0 as done-by-id: the batch is
content-bound (stewardship §1). rm-061's five ports are now COMPLETE in the worktree (uncommitted);
the render should mark rm-061's wave-0 portion satisfied and keep the cron trio remainder open.

## 7. How to verify wave 0 (all from repo root; focused tests only)

```bash
scripts/run_tests.sh tests/hermes_cli/test_secret_source_bootstrap.py   # B1 10/10
scripts/run_tests.sh tests/tools/test_skills_guard.py \
  tests/tui_gateway/test_skills_manage_install.py                       # B2 62/62 + 3/3
scripts/run_tests.sh tests/hermes_cli/test_update_lock.py \
  tests/hermes_cli/test_early_recovery.py                               # B3 46/46
cd apps/desktop && ../../node_modules/.bin/vitest run \
  electron/update-marker.test.ts src/lib/chat-messages/ src/lib/media.remote.test.ts  # B3+B4: 60 tests green
scripts/run_tests.sh tests/hermes_cli/test_gui_command.py               # B5 229/229
python3 -m py_compile scripts/ci/live_comment.py \
  scripts/ci/publish_e2e_evidence.py scripts/ci/timings_report.py       # Unit C
grep -n 'urlopen(' scripts/ci/*.py | grep -v timeout                    # → only the multiline :408 (timeout=60 next line)
```

Known-unrelated red at base: `tests/hermes_cli/test_plugins.py::TestPluginDiscovery::test_failed_discovery_is_not_cached`
fails at clean c4da06121c (verified by stashing the wave-0 edits); do not attribute to this batch.

import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import os from 'node:os'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const { matchKnownFailure, classifyWorkRoot, rules } = createRequire(import.meta.url)('../tests/install/e2e-assets/known-failures.cjs')
const classifier = path.resolve(import.meta.dirname, '../tests/install/e2e-assets/known-failures.cjs')

const lockedLog = [
  'error: failed to remove file `C:/install/venv/Lib/site-packages/../../Scripts/hermes.exe`: Access is denied. (os error 5)',
  "⚠ Git update failed: Command '['uv', 'pip', 'install', '-e', '.', '--quiet']' returned non-zero exit status 2.",
].join('\n')

const base = {
  platform: 'windows', phase: 'update', commit: 'a370ab8391ca5f8de7ebbc449f05cb0df36ade7c',
  installMethod: 'installer-script', updateMethod: 'hermes-update',
  error: 'E2E ASSERTION FAILED: hermes update exited 1 (expected 0)', logs: { update: lockedLog },
}

describe('known install failures', () => {
  it('recognizes the released launcher self-lock, not generic access denied', () => {
    expect(matchKnownFailure(base)?.id).toBe('windows-launcher-self-lock')
    expect(matchKnownFailure({ ...base, logs: { update: lockedLog.replaceAll('hermes.exe', 'other.exe') } })).toBeNull()
    expect(matchKnownFailure({ ...base, logs: { update: lockedLog.replace('(os error 5)', '(os error 32)') } })).toBeNull()
  })

  it.each([
    { platform: 'linux' }, { phase: 'install' }, { commit: 'v2026.3.12' },
    { commit: 'f'.repeat(40) }, { installMethod: 'desktop-installer@latest' },
    { updateMethod: 'installer-script' }, { error: 'E2E ASSERTION FAILED: update marker cleaned up' },
    { logs: {} },
  ])('rejects a different case or missing evidence: %j', change => {
    expect(matchKnownFailure({ ...base, ...change })).toBeNull()
  })

  it('matches manual-only app updates only for the three proven July script cases', () => {
    const sample = {
      ...base, commit: '7c1a029553d87c43ecff8a3821336bc95872213b',
      updateMethod: 'hermes-desktop-app-update',
      error: 'E2E ASSERTION FAILED: app driven via captured hermes desktop spec; update completed',
      logs: { desktop: '[hermes] [updates] no staged updater; surfacing manual `hermes update` for CLI install at C:/install\n[hermes] [updates] manual: hermes update\n' },
    }

    expect(matchKnownFailure(sample)?.id).toBe('windows-july-manual-app-update')
    expect(matchKnownFailure({ ...sample, installMethod: 'desktop-installer@latest' })).toBeNull()
    expect(matchKnownFailure({ ...sample, error: 'onboarding timed out' })).toBeNull()
    expect(matchKnownFailure({ ...sample, logs: { desktop: '[updates] manual: hermes update' } })).toBeNull()
  })

  // The pre-pm release classes (fix-queue item 226): the published
  // pm-era Setup.exe/dmg cannot install a pre-pm OLD tree, and the pre-pm
  // app self-replaces during first launch out from under Playwright.
  const PRE_PM = 'f97608f178d1ffeca59860195ab7da295f7c8e5f'

  const pmLockLog = [
    '2026-10-08T14:56:08.706006Z  INFO bootstrap.log: -> downloading uv 0.12.3 (win32-x64) stage=venv',
    "2026-10-08T14:56:10.675867Z  INFO bootstrap.log: [X] Cannot find path 'D:\\a\\hermes-agent\\hermes-desktop-gui-e2e\\hermes-home\\hermes-agent\\pm\\lock.json' because it does not exist. stage=venv",
    '2026-10-08T14:56:10.724851Z ERROR hermes_bootstrap_lib::bootstrap: bootstrap FAILED stage=Some("venv") error=Cannot find path \'D:\\a\\hermes-agent\\hermes-desktop-gui-e2e\\hermes-home\\hermes-agent\\pm\\lock.json\' because it does not exist.',
  ].join('\r\n')

  it('classifies the pre-pm Windows Setup.exe pm/lock.json install failure', () => {
    const sample = {
      platform: 'windows', phase: 'install', commit: PRE_PM,
      installMethod: 'desktop-installer@latest', updateMethod: 'hermes-update',
      error: 'E2E ASSERTION FAILED: AutoHotkey driver exited 0 (Install clicked, Launch clicked, app window seen)',
      logs: { bootstrap: pmLockLog },
    }
    expect(matchKnownFailure(sample)?.id).toBe('pre-pm-windows-setup-needs-pm-lock')
    // Update-phase re-runs of the Setup.exe classify too
    expect(matchKnownFailure({ ...sample, phase: 'update', installMethod: 'installer-script', updateMethod: 'desktop-installer@latest' })?.id).toBe('pre-pm-windows-setup-needs-pm-lock')
    // Fail-closed: a different OLD commit, a different stage, a different
    // filename, or a different method pair must NOT classify
    expect(matchKnownFailure({ ...sample, commit: 'a'.repeat(40) })).toBeNull()
    expect(matchKnownFailure({ ...sample, logs: { bootstrap: pmLockLog.replaceAll('"venv"', '"repository"') } })).toBeNull()
    expect(matchKnownFailure({ ...sample, logs: { bootstrap: pmLockLog.replaceAll('lock.json', 'other.json') } })).toBeNull()
    expect(matchKnownFailure({ ...sample, installMethod: 'installer-script', updateMethod: 'hermes-update' })).toBeNull()
    expect(matchKnownFailure({ ...sample, logs: { bootstrap: 'unrelated failure' } })).toBeNull()
  })

  it('classifies the pre-pm macOS dmg pm install failure', () => {
    const sample = {
      platform: 'macos', phase: 'install', commit: PRE_PM,
      installMethod: 'desktop-installer@latest', updateMethod: 'hermes-update',
      error: 'E2E ASSERTION FAILED: dmg bootstrap exited 1; transcript above',
      logs: { bootstrap: '2026-10-08T14:40:01.228057Z ERROR hermes_bootstrap_lib::bootstrap: bootstrap FAILED stage=Some("python-deps") error=pm install failed' },
    }
    expect(matchKnownFailure(sample)?.id).toBe('pre-pm-macos-setup-pm-install-failed')
    expect(matchKnownFailure({ ...sample, platform: 'windows' })).toBeNull()
    expect(matchKnownFailure({ ...sample, logs: { bootstrap: 'bootstrap FAILED stage=Some("products") error=pm install failed' } })).toBeNull()
    expect(matchKnownFailure({ ...sample, phase: 'update' })).toBeNull()
  })

  it('classifies the pre-pm linux app-update Playwright launch hang', () => {
    const hangLog = [
      '[+02:56] [launch-from-spec] launching /home/runner/work/_temp/hermes-installer-script-e2e/home/.hermes/hermes-agent/apps/desktop/release/linux-unpacked/Hermes (shape: packaged)',
      '[+05:56] electron.launch: Timeout 180000ms exceeded.',
      '[+05:56]   - <ws connecting> ws://127.0.0.1:46701/8dd906ea-127e-4166-a48b-5c017d2fdae8',
      '[+05:56]   - <ws connected> ws://127.0.0.1:46701/8dd906ea-127e-4166-a48b-5c017d2fdae8',
      '[+05:56]   - [pid=5934][out] [hermes] install stamp: 39a374d35288 (main) from ci',
    ].join('\n')
    const sample = {
      platform: 'linux', phase: 'update', commit: PRE_PM,
      installMethod: 'installer-script', updateMethod: 'hermes-desktop-app-update',
      error: 'E2E ASSERTION FAILED: app-driven update exited 1; transcript above',
      logs: { 'app-update': hangLog },
    }
    expect(matchKnownFailure(sample)?.id).toBe('pre-pm-linux-app-update-self-relaunch')
    // Fail-closed: a firstWindow timeout (window appeared, different class) or
    // a different OS/method must NOT classify
    expect(matchKnownFailure({ ...sample, logs: { 'app-update': hangLog.replace('electron.launch: Timeout 180000ms exceeded.', 'firstWindow: Timeout 120000ms') } })).toBeNull()
    expect(matchKnownFailure({ ...sample, platform: 'macos' })).toBeNull()
    expect(matchKnownFailure({ ...sample, updateMethod: 'hermes-update' })).toBeNull()
  })

  it('classifyWorkRoot reads posix state from an explicit OLD sha and logs dir', () => {
    const root = mkdtempSync(path.join(os.tmpdir(), 'known-install-'))
    try {
      mkdirSync(path.join(root, 'logs'), { recursive: true })
      writeFileSync(path.join(root, 'logs', 'app-update.log'), 'electron.launch: Timeout 180000ms exceeded.\n<ws connected> ws://127.0.0.1:46701/8dd906ea\n')
      const receipt = classifyWorkRoot(root, 'installer-script', 'hermes-desktop-app-update',
        'E2E ASSERTION FAILED: app-driven update exited 1; transcript above',
        'linux', 'update', PRE_PM, path.join(root, 'logs'))
      expect(receipt?.id).toBe('pre-pm-linux-app-update-self-relaunch')
      // No explicit sha -> falls back to shas.json (absent here -> throw, the
      // posix drivers always pass the sha)
      expect(() => classifyWorkRoot(root, 'installer-script', 'hermes-desktop-app-update', 'x', 'linux', 'update')).toThrow()
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('CLI writes a receipt and exits zero only on a confirmed match', () => {
    const root = mkdtempSync(path.join(os.tmpdir(), 'known-install-'))

    try {
      mkdirSync(path.join(root, 'logs'))
      writeFileSync(path.join(root, 'shas.json'), '\uFEFF' + JSON.stringify({ old: base.commit, current: 'f'.repeat(40), old_ref: 'v2026.3.12' }))
      writeFileSync(path.join(root, 'logs/update.log'), lockedLog)
      const args = [classifier, root, base.installMethod, base.updateMethod, base.error]
      expect(spawnSync(process.execPath, args).status).toBe(0)
      expect(JSON.parse(readFileSync(path.join(root, 'known-failure.json'), 'utf8')).id).toBe('windows-launcher-self-lock')
      writeFileSync(path.join(root, 'logs/update.log'), 'an unrelated failure')
      expect(spawnSync(process.execPath, args).status).toBe(1)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })
})

it('renders known receipts as footnotes, without suppressing a red job', async () => {
  const modulePath = new URL('../scripts/sandbox/generate-e2e-matrix.mjs', import.meta.url).href
  const { renderMarkdownResults, legId } = await import(/* @vite-ignore */ modulePath)
  const name = 'windows: installer-script -> hermes-update (v2026.3.12 -> HEAD)'
  const artifacts = new Map([[`install-e2e-known-${rules[0].id}--${legId(name)}`, 42]])
  const known = renderMarkdownResults([{ name: name + ' / e2e', conclusion: 'success' }], [], artifacts)
  expect(known).toContain('0 passed, 0 failed, 1 known failures')
  expect(known).toContain('known [^1]')
  expect(known).toContain(`[^1]: **${rules[0].title}.**`)
  const failed = renderMarkdownResults([{ name: name + ' / e2e', conclusion: 'failure' }], [], artifacts)
  expect(failed).toContain('0 passed, 1 failed, 0 known failures')
  expect(failed).not.toContain('known [^1]')
  const passed = renderMarkdownResults([{ name: name + ' / e2e', conclusion: 'success' }])
  expect(passed).toContain('1 passed, 0 failed, 0 known failures')
})

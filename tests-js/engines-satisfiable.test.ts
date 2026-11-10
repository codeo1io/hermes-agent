import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { load as loadYaml } from 'js-yaml'

import { describe, test } from 'vitest'

/**
 * The manifest's `engines` must be satisfiable by a toolchain we can actually ship.
 *
 * `engine-strict=true` in `.npmrc` makes `engines` a hard gate on every
 * `npm ci` / `npm install`. A floor nobody's toolchain can meet is a total
 * install outage, not a strict-hygiene win. These tests live on the JS lane
 * (not the Python suite) precisely because a JS-only `engines` bump selects
 * only this lane — the Python copy silently never ran for the diff shape
 * that mattered. Deliberately behavioral: every test asserts a relationship
 * between the floor we declare and the toolchain that must satisfy it.
 */

const REPO_ROOT = path.resolve(__dirname, '..')

// npm releases bundled with a Node major, newest-per-major. Not a catalog
// snapshot: the point is that *some* real, shipping toolchain must clear the
// floor, and these are the ones users actually arrive with.
interface Engines {
  node?: string
  npm?: string
}

interface Manifest {
  engines?: Engines
}

interface Lockfile {
  packages?: Record<string, { engines?: { node?: string } }>
}

function readJson<T>(relativePath: string): T {
  return JSON.parse(fs.readFileSync(path.join(REPO_ROOT, relativePath), 'utf-8')) as T
}

function readText(relativePath: string): string {
  return fs.readFileSync(path.join(REPO_ROOT, relativePath), 'utf-8')
}

function parseVersion(version: string): [number, number, number] {
  const [major = 0, minor = 0, patch = 0] = version.split('-')[0].split('.').map(Number)
  return [major, minor, patch]
}

function compare(left: string, right: string): number {
  const have = parseVersion(left)
  const want = parseVersion(right)
  for (let index = 0; index < have.length; index += 1) {
    if (have[index] !== want[index]) {
      return have[index] - want[index]
    }
  }
  return 0
}

function satisfiesClause(version: string, clause: string): boolean {
  assert.match(
    clause,
    /^(?:\^|>=|<=|>|<|=)?\d+(?:\.\d+){0,2}$/,
    `unsupported semver clause: ${clause}`
  )
  if (clause.startsWith('^')) {
    const bound = clause.slice(1)
    return parseVersion(version)[0] === parseVersion(bound)[0] && compare(version, bound) >= 0
  }
  const match = clause.match(/^(>=|<=|>|<|=)?(.+)$/)
  assert.ok(match)
  const [, operator = '=', bound] = match
  const result = compare(version, bound)
  return operator === '>='
    ? result >= 0
    : operator === '<='
      ? result <= 0
      : operator === '>'
        ? result > 0
        : operator === '<'
          ? result < 0
          : result === 0
}

function satisfiesRange(version: string, range: string): boolean {
  const alternatives = range.split('||').map(alternative => alternative.trim().split(/\s+/))
  alternatives.flat().forEach(clause => satisfiesClause(version, clause))
  return alternatives.some(clauses => clauses.every(clause => satisfiesClause(version, clause)))
}

/** Normalize the wilder styles real deps publish (`>= 10`, `>=v12`, `6.x`) so the
 * strict evaluator above can read them — and still fail loudly on anything else. */
function normalizeRange(spec: string): string {
  return spec
    .replace(/(>=|<=|>|<|\^|~|=)\s+/g, '$1')
    .replace(/(>=|<=|>|<|\^|~|=)v/g, '$1')
    .replace(/(\d+)\.[x*](?:\.[x*])?/g, '$1.0.0')
}

const rootManifest = readJson<Manifest>('package.json')
// Upstream v0.23.1 switched the workspace npm→pnpm (7062229090a):
// package-lock.json is gone; pnpm-lock.yaml is the lock of record.
const lockfile = loadYaml(
  fs.readFileSync(path.join(REPO_ROOT, 'pnpm-lock.yaml'), 'utf-8'),
) as Lockfile

function engines(label: string): Engines {
  assert.ok(rootManifest.engines?.node && rootManifest.engines?.npm, `${label} must declare engines`)
  return rootManifest.engines
}

const rootEngines = engines('root package.json')

function managedNodeMajor(): number {
  // pm owns node provisioning (pm/packages.py resolves the newest LTS from
  // nodejs.org at install time), so there is no static pin to read: the
  // managed runtime is "the current LTS line". The contract that keeps the
  // manifest honest is the open >=major.0.0 arm — its major is what a fresh
  // pm install lands on, and it must dominate every caret arm.
  const openArms = rootEngines.node!.split('||').map(arm => arm.trim()).filter(arm => arm.startsWith('>='))
  assert.ok(openArms.length > 0, `engines.node ${rootEngines.node} has no open >=major arm for pm-managed LTS installs`)
  const major = parseVersion(openArms[openArms.length - 1].replace(/^>=/, ''))[0]
  for (const arm of rootEngines.node!.split('||').map(a => a.trim())) {
    if (arm.startsWith('^')) {
      const caretMajor = parseVersion(arm.replace(/^\^/, ''))[0]
      assert.ok(
        caretMajor <= major,
        `engines arm ${arm} outgrows the open ${openArms[openArms.length - 1]} arm a pm-managed install satisfies`
      )
    }
  }
  return major
}

describe('Engines are satisfiable', () => {
  test('npm is refused (pnpm is the installer)', () => {
    // Upstream v0.23.1 switched the workspaces npm→pnpm (7062229090a):
    // engines.npm is now a prose refusal, so a bare `npm install` dies at
    // the engines gate instead of silently building a second lockfile tree.
    assert.match(
      rootEngines.npm ?? '',
      /refused/i,
      `engines.npm must refuse npm (got ${JSON.stringify(rootEngines.npm)})`,
    )
  })

  test('pnpm range is satisfiable by the pnpm 12 line', () => {
    const pnpmRange = (rootManifest.engines as Record<string, string | undefined>).pnpm
    assert.ok(pnpmRange, 'engines.pnpm must be declared (pnpm is the installer)')
    assert.ok(
      satisfiesRange('12.999.999', pnpmRange),
      `engines.pnpm is ${pnpmRange}, which no pnpm 12.x satisfies`,
    )
  })

  test('node floor is met by the managed runtime', () => {
    // pm provisions the newest LTS line, not {major}.0.0; use a high
    // representative release so ranges enumerating LTS lines check correctly.
    const major = managedNodeMajor()
    assert.ok(
      satisfiesRange(`${major}.999.999`, rootEngines.node!),
      `engines.node is ${rootEngines.node} but pm provisions the Node ${major}.x LTS line`
    )
  })

  test('managed Node line satisfies the root floor', () => {
    const major = managedNodeMajor()
    assert.ok(major >= 26, `managed Node major ${major} below the >=26 workspace floor`)
  })

  test('desktop node floor is not stricter than its toolchain', () => {
    // Vite is the real constraint. Raising the desktop floor beyond it
    // force-migrates user toolchains for no dependency reason. Upstream
    // 4d5c6cfb0c0 (adopted with v0.22.6) moved the whole workspace to a
    // single '>=26' floor — PM provisions Node 26.12.1 — so the guard now
    // asserts the desktop floor stays satisfiable by the pm-managed LTS
    // line and no stricter than the root workspace's own floor.
    const desktop = readJson<Manifest>('apps/desktop/package.json')
    assert.ok(
      satisfiesRange('26.12.1', desktop.engines?.node ?? ''),
      `apps/desktop engines.node is ${desktop.engines?.node}, stricter than the pm-managed Node 26 LTS its build tools require`
    )
    assert.ok(
      satisfiesRange('26.0.0', desktop.engines?.node ?? ''),
      `apps/desktop engines.node is ${desktop.engines?.node}, above the workspace floor ${rootEngines.node}`
    )
  })
})

describe('Excluded npm band (historical: npm refused since v0.23.1)', () => {
  // npm 11.10–11.16 ignored min-release-age-exclude and died at ETARGET —
  // the reason the old floor excluded them. npm is refused outright now;
  // the durable pin is that the refusal STAYS a refusal.
  test('the npm engines field never returns to a satisfiable range', () => {
    assert.doesNotMatch(
      rootEngines.npm ?? '',
      /\d+\.\d+/,
      'engines.npm became a semver range again — npm is not the installer',
    )
  })
})

describe('Manifest mirrors', () => {
  test('lockfile parses with a packages section', () => {
    // pnpm has no root '' mirror entry; the structural contract is that the
    // lock of record parses and carries the locked tree the floor test walks.
    assert.ok(Object.keys(lockfile.packages ?? {}).length > 0, 'pnpm-lock.yaml has no packages')
  })
})

describe('Declared floors clear the locked tree', () => {
  // The class of outage this pins: engines.node and the installer gates are
  // hand-maintained while the *real* floor is the strictest locked dependency.
  // When they drift, a user's Node clears every gate we own and then dies at
  // `npm install` with EBADENGINE under engine-strict=true (Aug 2026: @babel/*
  // 8.x required ^22.18.0 || >=24.11.0 while the manifest said ^24.0.0).

  test('every engines arm floor clears every locked dependency', () => {
    const lockedRanges = new Map<string, string>()
    for (const [pkgPath, meta] of Object.entries(lockfile.packages ?? {})) {
      const nodeRange = meta?.engines?.node
      if (typeof nodeRange === 'string' && nodeRange.trim() !== '' && nodeRange.trim() !== '*') {
        lockedRanges.set(nodeRange, pkgPath)
      }
    }
    const violations: Array<[string, string, string]> = []
    for (const arm of rootEngines.node!.split('||')) {
      const floor = arm.trim().replace(/^(\^|>=|=)/, '')
      for (const [depRange, example] of lockedRanges) {
        if (!satisfiesRange(floor, normalizeRange(depRange))) {
          violations.push([floor, depRange, example])
        }
      }
    }
    assert.deepEqual(violations, [])
  })

  test('installers delegate node provisioning to pm', () => {
    // The class of drift this pins (Oct 2026): the manifest grew a ^22.22.0
    // arm while node provisioning moved from the installers to `pm` — the old
    // NODE_VERSION pin and the per-arm gates went away by design (install.sh
    // and install.ps1 both say heavy dependencies "are pm's job"). What must
    // NOT come back: a static installer pin or a laxer hand-maintained gate
    // that accepts a Node the manifest then rejects.
    const installSh = readText('scripts/install.sh')
    const installPs1 = readText('scripts/install.ps1')
    assert.ok(!/^NODE_VERSION=/m.test(installSh), 'install.sh must not pin NODE_VERSION (pm owns node)')
    assert.ok(!/node_satisfies_build\s*\(\s*\)/.test(installSh), 'install.sh must not re-grow node gates')
    assert.ok(!/function Test-NodeVersionOk/.test(installPs1), 'install.ps1 must not re-grow node gates')
    assert.match(installSh, /are pm's job/, 'install.sh must keep the pm delegation marker')
    assert.match(installPs1, /are pm's job/, 'install.ps1 must keep the pm delegation marker')
  })
})

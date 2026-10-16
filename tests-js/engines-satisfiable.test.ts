import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

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
const STOCK_NPM_BY_NODE_MAJOR: Record<number, string> = {
  20: '10.8.2',
  22: '10.9.8',
  24: '11.16.0',
  26: '11.17.0',
}

interface Engines {
  node?: string
  npm?: string
}

interface Manifest {
  engines?: Engines
}

interface Lockfile {
  packages?: Record<string, { engines?: Engines }>
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
const lockfile = readJson<Lockfile>('package-lock.json')

function engines(label: string): Engines {
  assert.ok(rootManifest.engines?.node && rootManifest.engines?.npm, `${label} must declare engines`)

  return rootManifest.engines
}

const rootEngines = engines('root package.json')

function managedNodeMajor(): number {
  const installSh = readText('scripts/install.sh')

  for (const line of installSh.split('\n')) {
    if (line.startsWith('NODE_VERSION=')) {
      return Number.parseInt(line.split('=')[1].trim().replace(/["']/g, ''), 10)
    }
  }

  assert.fail('install.sh does not define NODE_VERSION')
}

describe('Engines are satisfiable', () => {
  test('npm floor is met by a shipping Node', () => {
    // Without this, a fresh install cannot run `npm ci` at all: the installer
    // provisions a Node from nodejs.org and immediately uses its bundled npm.
    const satisfying = Object.entries(STOCK_NPM_BY_NODE_MAJOR).filter(([, npm]) =>
      satisfiesRange(npm, rootEngines.npm!)
    )

    assert.ok(satisfying.length > 0, `engines.npm is ${rootEngines.npm}, which no shipping Node bundles`)
  })

  test('node floor is met by the managed runtime', () => {
    // install.sh fetches latest-v{major}.x, not {major}.0.0; use a high
    // representative release so ranges enumerating LTS lines check correctly.
    const major = managedNodeMajor()
    assert.ok(
      satisfiesRange(`${major}.999.999`, rootEngines.node!),
      `engines.node is ${rootEngines.node} but install.sh provisions Node ${major}.x`
    )
  })

  test('managed Node bundles an npm the engines accept', () => {
    // Node 22 bundles npm 11.16.0 — inside the excluded 11.10–11.16 band:
    // fresh Hermes-managed installs die at `npm ci` with EBADENGINE.
    const major = managedNodeMajor()
    const stockNpm = STOCK_NPM_BY_NODE_MAJOR[major]
    assert.ok(stockNpm, `install.sh NODE_VERSION=${major} is not in the known stock map`)
    assert.ok(
      satisfiesRange(stockNpm, rootEngines.npm!),
      `install.sh provisions Node ${major}.x (stock npm ${stockNpm}) but engines.npm is ${rootEngines.npm}`
    )
  })

  test('desktop node floor is not stricter than its toolchain', () => {
    // Vite is the real constraint. Raising the desktop floor beyond it
    // force-migrates user toolchains for no dependency reason.
    const desktop = readJson<Manifest>('apps/desktop/package.json')
    assert.ok(
      satisfiesRange('22.22.0', desktop.engines?.node ?? ''),
      `apps/desktop engines.node is ${desktop.engines?.node}, stricter than its build tools require`
    )
  })
})

describe('Excluded npm band', () => {
  // npm 11.10–11.16 honor `min-release-age` but ignore `min-release-age-exclude`;
  // `.npmrc` sets both, so that band applies the age gate to exempted packages
  // and installs fail with ETARGET. The floor must keep excluding them.
  test.each(['11.10.0', '11.12.1', '11.16.0'])('rejects npm %s (ignores the exclude list)', badNpm => {
    assert.ok(!satisfiesRange(badNpm, rootEngines.npm!))
  })

  test.each(['10.9.8', '11.17.0', '12.0.2'])('accepts npm %s (handles .npmrc correctly)', goodNpm => {
    assert.ok(satisfiesRange(goodNpm, rootEngines.npm!))
  })
})

describe('Manifest mirrors', () => {
  test('lockfile engines match the manifest', () => {
    // A stale lockfile mirror re-imposes the old floor on `npm ci`.
    assert.deepEqual(lockfile.packages?.['']?.engines, rootManifest.engines)
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

  test('installer gates match the manifest arms', () => {
    // install.sh's node_satisfies_build and install.ps1's Test-NodeVersionOk
    // must encode the same floors as engines.node — a laxer gate accepts a
    // Node that npm then rejects.
    const installSh = readText('scripts/install.sh')
    const installPs1 = readText('scripts/install.ps1')

    for (const arm of rootEngines.node!.split('||')) {
      const trimmed = arm.trim()
      const [major, minor] = parseVersion(trimmed.replace(/^(\^|>=|=)/, ''))

      if (trimmed.startsWith('^') && minor > 0) {
        const shGate = `[ "$major" -eq ${major} ] && [ "$minor" -ge ${minor} ]`
        const ps1Gate = `if ($v.Major -eq ${major}) { return ($v.Minor -ge ${minor}) }`
        assert.ok(installSh.includes(shGate), `engines arm ${trimmed} has no matching install.sh gate`)
        assert.ok(installPs1.includes(ps1Gate), `engines arm ${trimmed} has no matching install.ps1 gate`)
      }
    }
  })
})

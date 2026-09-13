import type { TestProjectConfiguration } from 'vitest/config'
import { defineConfig } from 'vitest/config'

const reactUi: TestProjectConfiguration = {
  extends: './vite.config.ts',
  test: {
    name: 'ui',
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    globals: true,
    // The first test in each file pays jsdom env init + full module transform,
    // which can exceed vitest's 5000ms default under CI/load. 15s gave the
    // cold start headroom on GitHub's 32-core runners, but the self-hosted
    // runner is 14 cores and run-workspace-checks.mjs runs ALL workspace
    // checks concurrently — each check sizes its own vitest pool from the
    // core count, so ~10 pools oversubscribe the box and the cold-start
    // test exceeds 15s (observed 15012ms/15044ms timeouts on tests that
    // pass in 8-13s idle, PR CI run 33835883747). 45s keeps the headroom
    // without masking genuinely hung tests (total file durations are
    // 23-29s, so a real hang still fails well within a run).
    testTimeout: 45_000
  }
}

const electronNative: TestProjectConfiguration = {
  test: {
    name: 'electron',
    environment: 'node',
    include: ['electron/**/*.test.ts', 'scripts/**.test.{ts,mjs}'],
    exclude: ['scripts/run-short-session-hang-repro.test.mjs'],
    // Real git subprocesses, several per test. On a shared self-hosted
    // runner under concurrent load a test can exceed vitest's 5000ms
    // default while doing exactly its normal work (observed 3.1-3.5s
    // quiet, >5s under load). The ui project raised its timeout for the
    // same reason; keep these tests' real-per-work margin too.
    testTimeout: 15_000
  }
}

export default defineConfig({
  test: {
    projects: [reactUi, electronNative]
  }
})

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
    // `e2e/**/*.unit.test.ts` is the e2e HELPERS, not the specs: plain node
    // modules that should be provable without booting Electron. Playwright
    // ignores the same pattern so they run in exactly one runner.
    include: ['electron/**/*.test.ts', 'scripts/**.test.{ts,mjs}', 'e2e/**/*.unit.test.ts'],
    // These use node:test and have dedicated npm scripts, not Vitest suites.
    exclude: ['scripts/run-short-session-hang-repro.test.mjs', 'scripts/tasks-scroll.test.mjs']
  }
}

export default defineConfig({
  test: {
    projects: [reactUi, electronNative]
  }
})

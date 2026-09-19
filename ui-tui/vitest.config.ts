import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    exclude: ['dist/**', 'node_modules/**'],
    // Shared self-hosted runner: sibling conductor suites hold load 40-100,
    // so vitest's 5s default produced a rotating cast of timeout failures
    // (a different random subset each run, tree unchanged). 15s matches the
    // apps/desktop projects.
    testTimeout: 15_000
  }
})

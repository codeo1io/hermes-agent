import { defineConfig } from "vitest/config";
import babel from "@rolldown/plugin-babel";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";

/** Same component/hook-scoped compiler preset as vite.config.ts. */
function compilerPreset() {
  const preset = reactCompilerPreset();
  preset.rolldown.filter.code = /\/>|<\/|from\s*['"][^'"]*react/;
  return preset;
}
import path from "path";

export default defineConfig({
  plugins: [react(), babel({ presets: [compilerPreset()] })],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
    // The dashboard suites render React under fake timers; on a shared
    // self-hosted runner with all workspace checks running concurrently a
    // test can exceed vitest's 5000ms default while doing its normal work
    // (observed intermittent ChatPage timeouts only under full concurrent
    // load, 6/6 green when the host is quiet). Same margin the ui project
    // already uses.
    testTimeout: 15_000,
  },
});

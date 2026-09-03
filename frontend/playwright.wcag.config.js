/**
 * Playwright config for the WCAG real-browser accessibility audit.
 *
 * Uses SIM mode (VITE_SIM=true) so no backend server is needed —
 * all data comes from sim.js synthetic fixtures.  The compliance
 * persona provides access to all workflow tabs.
 *
 * Run with:
 *   ACP_E2E_CHROMIUM=/opt/pw-browsers/chromium-1194/chrome-linux/chrome \
 *     npx playwright test --config=playwright.wcag.config.js
 */
import { defineConfig, devices } from '@playwright/test'

const UI_PORT = 5176  // distinct from the dev (5173) and pipeline-e2e (5174) ports

export default defineConfig({
  testDir: './e2e',
  testMatch: 'wcag-a11y.spec.js',
  workers: 1,
  fullyParallel: false,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  reporter: [['list']],

  use: {
    baseURL: `http://127.0.0.1:${UI_PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },

  projects: [{
    name: 'chromium',
    use: {
      ...devices['Desktop Chrome'],
      // Use the pre-installed Chromium from the sandbox environment.
      // The env var ACP_E2E_CHROMIUM is the same override the main config supports.
      ...(process.env.ACP_E2E_CHROMIUM
        ? { launchOptions: { executablePath: process.env.ACP_E2E_CHROMIUM } }
        : {}),
    },
  }],

  webServer: [{
    // SIM mode: VITE_SIM anything other than 'false' activates the in-process sim.
    // api.js reads `import.meta.env.VITE_SIM !== 'false'`, so 'true' or any other
    // truthy string works.  No backend process is started.
    command: `npx vite --port ${UI_PORT} --host 127.0.0.1`,
    url: `http://127.0.0.1:${UI_PORT}`,
    env: { VITE_SIM: 'true' },
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: 'pipe',
    stderr: 'pipe',
  }],
})

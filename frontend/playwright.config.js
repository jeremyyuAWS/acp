import { defineConfig, devices } from '@playwright/test'

// Off the dev ports (5173 / 8077) on purpose, so a run does not collide with — or quietly
// borrow — a ./scripts/run.sh stack someone already has up. Borrowing the dev API would be
// the worse failure: the suite would pass against whatever corpus and store that one holds.
const UI_PORT = parseInt(process.env.ACP_E2E_UI_PORT || '5174')
const API_PORT = parseInt(process.env.ACP_E2E_API_PORT || '8078')
const API = `http://127.0.0.1:${API_PORT}`

export default defineConfig({
  testDir: './e2e',
  // Serial. The backend keeps one active local scan per source and rejects a second
  // ("Discovery already active for source 'local'"), so parallel specs would fight over it.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // The html reporter is what writes playwright-report/, which the CI job uploads on failure.
  // Without it that upload finds nothing and warns instead — the artifact you actually want to
  // read is missing exactly when a run failed. open:'never' keeps it from trying to launch a
  // browser on the runner.
  reporter: process.env.CI
    ? [['github'], ['list'], ['html', { open: 'never' }]]
    : [['list']],
  timeout: 120_000,
  expect: { timeout: 15_000 },

  use: {
    baseURL: `http://127.0.0.1:${UI_PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  // CI runs `playwright install chromium` and gets the build this @playwright/test expects, so
  // the override stays unset there. Set ACP_E2E_CHROMIUM to a chrome binary when the sandbox
  // you are in ships a pre-installed browser from a different Playwright release — otherwise
  // launch fails with "Executable doesn't exist at .../chromium_headless_shell-<n>".
  projects: [{
    name: 'chromium',
    use: {
      ...devices['Desktop Chrome'],
      ...(process.env.ACP_E2E_CHROMIUM
        ? { launchOptions: { executablePath: process.env.ACP_E2E_CHROMIUM } }
        : {}),
    },
  }],

  webServer: [
    {
      command: '../scripts/e2e-api.sh',
      url: `${API}/healthz`,
      env: { ACP_E2E_API_PORT: String(API_PORT) },
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // --host 127.0.0.1 is required, not cosmetic. Vite otherwise binds the hostname
      // "localhost", and Node ≥17 resolves that to ::1 first wherever IPv6 exists — so on a
      // GitHub runner vite listens on [::1]:5174 while the readiness probe below dials
      // 127.0.0.1 and never connects. That failure is silent in the worst way: vite prints its
      // usual "ready" banner, no request is ever logged, and the job dies 120s later on
      // "Timed out waiting from config.webServer". It cannot reproduce in a container with no
      // IPv6, where "localhost" resolves to 127.0.0.1 and everything passes. Binding the
      // address explicitly — as the API side already does — takes resolution order out of it.
      command: `npx vite --port ${UI_PORT} --host 127.0.0.1`,
      url: `http://127.0.0.1:${UI_PORT}`,
      // VITE_SIM is the one that matters. sim.js reads `import.meta.env.VITE_SIM !== 'false'`,
      // so simulation is ON unless this exact string is set — and in SIM mode api.js serves
      // synthetic fixtures and never calls the backend at all. Without this the suite would
      // drive a mock, go green, and assert nothing about the real pipeline.
      env: { VITE_SIM: 'false', VITE_API: API },
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})

/**
 * A platform-admin write in the SIM build must be visibly non-real, never a fake success.
 *
 * Why this exists. #85's honesty guard in Settings.jsx compares the RESPONSE to the REQUEST:
 *
 *     const drift = Object.keys(want).filter((k) => (s?.[k] ?? '') !== want[k])
 *
 * That catches a real backend's silent no-op. It could never catch SIM's, because SIM's
 * `updateSettings` CONSTRUCTED the response from the request — `{ ...defaults, ...patch }` — so
 * `drift` was empty by construction and the panel always printed
 * "✓ endpoint switched — takes effect on every replica within ~30s". The one build where a fake
 * success is possible was the one build the guard was structurally blind to.
 *
 * And SIM is not a corner: sim.js is `VITE_SIM !== 'false'`, so SIM is ON by default and only
 * deploy/public/Dockerfile turns it off. The Netlify site and `npm run dev` are both SIM. The
 * Apply button was clicked on one of them for a production vision-model fix on 2026-07-30 and
 * again on 2026-07-31; both times the panel said it worked and production never changed.
 *
 * The render test below is the one that matters — it drives the real panel through the real SIM
 * api.js and reads what a user would read. The source assertions pin the parts a refactor could
 * quietly drop.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

afterEach(unmountAll)

// ── The panel, driven for real under SIM ──────────────────────────────────────────
// No api.js mock on purpose. The defect lived in the SIM stub itself, so a test that replaces it
// tests the wrong thing; SIM is also the default (VITE_SIM unset here), which is the whole point.
const { default: Settings } = await import('./Settings.jsx')

// api.js's sim() resolves after 220ms of REAL time, so settling here has to cross the clock —
// flushing microtasks alone leaves the panel on "Loading…" and every query below finds nothing.
const settle = async (ms = 320) => {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
  for (let k = 0; k < 3; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const byText = (root, sel, t) => [...root.querySelectorAll(sel)].find((e) => e.textContent.trim() === t)

const openStorageTab = async () => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(Settings, { onClose: () => {} })) })
  await settle()
  await click(byText(container, 'button[role="tab"]', 'Remediated storage'))
  await settle()
  return container
}

describe('the SIM build cannot report a platform write it did not make', () => {
  it('answers Apply with "nothing was written" instead of "✓ endpoint switched"', async () => {
    const container = await openStorageTab()
    const apply = byText(container, 'button', 'Apply')
    expect(apply, 'the AI-endpoint Apply button should be on the Remediated storage tab').toBeTruthy()

    await click(apply)
    await settle()

    // Assert on the OUTCOME lines, not the whole panel: the static copy above the field describes
    // the real feature ("takes effect on every replica within ~30 seconds") and is allowed to.
    // What was never allowed is the panel reporting that as something that just happened.
    const outcome = [...container.querySelectorAll('p[role="status"]')]
      .map((p) => p.textContent).join(' ')
    // The exact sentence that cost two debugging cycles — a ~30s rollout across every replica,
    // claimed by a build that made no request at all.
    expect(outcome).not.toContain('endpoint switched')
    expect(outcome).not.toContain('takes effect on every replica')
    expect(outcome).toContain('SIM — nothing was written')
    // ...and it must not read as a save of any kind. No ✓ in any status line the save produced.
    expect(outcome).not.toContain('✓')
  })

  it('badges the whole admin panel before any button is pressed', async () => {
    const container = await openStorageTab()
    // Before the first save, not only in the outcome line — the outcome line was the liar.
    expect(container.textContent).toContain('every setting here is simulated')
    expect(container.textContent).toMatch(/no production endpoint, vision model/)
  })

  it('the badge is on the panel itself, so every tab carries it', async () => {
    const { container, root } = createTestRoot()
    await act(async () => { root.render(createElement(Settings, { onClose: () => {} })) })
    await settle()
    // Default tab is Scoring rules — never went near the settings write paths.
    expect(container.textContent).toContain('every setting here is simulated')
  })

  it('renders the simulated outcome in its own tone, not as a platform error', async () => {
    const container = await openStorageTab()
    await click(byText(container, 'button', 'Apply'))
    await settle()
    const p = [...container.querySelectorAll('p[role="status"]')].find((e) => e.textContent.includes('SIM'))
    // Amber (the ReadOnlyNotice tone), not the red reserved for something that actually failed.
    expect(p.style.color).toBe('rgb(107, 74, 11)')
  })
})

// ── The API layer's own claim ─────────────────────────────────────────────────────
describe('the SIM stubs mark their answers as simulated', () => {
  beforeEach(() => { vi.resetModules() })
  afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks() })

  it('updateSettings flags every response, so no caller can mistake it for a save', async () => {
    const { updateSettings } = await import('./api.js')
    const s = await updateSettings({ ai_base_url: 'http://gpu.internal:11434', ai_vision_model: 'qwen2.5vl:7b' })
    expect(s.simulated).toBe(true)
  })

  it('getSettings flags its reads too — a reload must not look like a persisted write', async () => {
    const { getSettings } = await import('./api.js')
    expect((await getSettings()).simulated).toBe(true)
  })

  it('putAiProvider flags its response', async () => {
    const { putAiProvider } = await import('./api.js')
    expect((await putAiProvider({ provider: 'azure_openai' })).simulated).toBe(true)
  })

  it('the real build is untouched — no flag, so a genuine save still reports ✓', async () => {
    vi.stubEnv('VITE_SIM', 'false')
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
      ok: true, status: 200, json: () => Promise.resolve({ ai_vision_model: 'moondream' }),
    })))
    const { updateSettings } = await import('./api.js')
    const s = await updateSettings({ ai_vision_model: 'moondream' })
    expect(s.simulated).toBeUndefined()
    expect(s.ai_vision_model).toBe('moondream')
  })
})

// ── The parts a refactor could quietly drop ───────────────────────────────────────
describe('the guard cannot be reintroduced by accident', () => {
  it('the simulated check runs BEFORE the drift check, which cannot see it', () => {
    const s = read('Settings.jsx')
    const body = s.slice(s.indexOf('const saveEndpoint'), s.indexOf('const useDeployDefault'))
    const simulated = body.indexOf('s?.simulated')
    const drift = body.indexOf('drift.length')
    expect(simulated).toBeGreaterThan(-1)
    // Order matters: SIM builds its response from the request, so `drift` is always empty there
    // and reaching it first would print the success message.
    expect(simulated).toBeLessThan(drift)
  })

  it('every settings write in the panel routes its success message through one place', () => {
    const s = read('Settings.jsx')
    expect(s).toMatch(/const wrote = \(s, ok\) => \(s\?\.simulated \? SIM_NOT_WRITTEN : ok\)/)
    // the folder save, both toggles and the provider save all use it
    expect(s).toMatch(/setMsg\(wrote\(s, '✓ saved'\)\)/)
    expect(s.match(/setMsg\(wrote\(s, ''\)\)/g) || []).toHaveLength(2)   // both toggles
    expect(s).toMatch(/setNote\(wrote\(res,/)
  })

  it('the SIM stub no longer echoes the caller\'s patch back as the server\'s answer', () => {
    const api = read('api.js')
    const stub = api.slice(api.indexOf('export const updateSettings'),
                           api.indexOf('export const updateSettings') + 400)
    // This exact shape is the defect: the response built out of the request.
    expect(stub).not.toMatch(/drive_mirror_folder: 'Remediated', \.\.\.patch/)
    expect(stub).toMatch(/simulated: true/)
  })

  it('a simulated outcome gets its own colour rather than green or red', () => {
    const s = read('Settings.jsx')
    expect(s).toMatch(/const msgColor =/)
    // and no call site still hard-codes the old two-way test
    expect(s).not.toMatch(/startsWith\('✓'\) \? '#3B6D11' : '#A32D2D'/)
  })

  it('the panel badge is gated on the build flag, not on a response that may never arrive', () => {
    const s = read('Settings.jsx')
    expect(s).toMatch(/import \{ SIM \} from '\.\/sim\.js'/)
    expect(s).toMatch(/\{SIM && <SimNotice \/>\}/)
    // above the subtabs — it is true of every tab, not just the settings ones
    expect(s.indexOf('{SIM && <SimNotice />}')).toBeLessThan(s.indexOf('className="subtabs"'))
  })
})

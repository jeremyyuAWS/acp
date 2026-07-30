/**
 * The AI-endpoint settings form: the vision model must actually reach the server, and a save
 * that fails must not leave the form asserting a value production does not hold.
 *
 * Why this exists. On 2026-07-29 `vision_available` was false because the configured vision
 * model (`qwen2.5vl:7b`) was absent from the Ollama container, which had `moondream` baked in
 * all along. Changing the field to `moondream` in this form appeared to do nothing three times
 * over, and the leading theory was that the client never sent `ai_vision_model` in the PUT.
 * It did — so pin that down, because it is the assumption a future reader will re-make. The
 * defects that were real are the silent ones: a rejected save left the typed value on screen
 * with the old value still live, and the only notice rendered below the whole providers
 * section, out of sight of the Apply button.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('the vision model reaches the server in the settings PUT', () => {
  beforeEach(() => { vi.resetModules(); vi.stubEnv('VITE_SIM', 'false') })
  afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks() })

  it('PUTs ai_vision_model in the request body, not just ai_base_url', async () => {
    const calls = []
    vi.stubGlobal('fetch', vi.fn((url, opts) => {
      calls.push({ url, opts })
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
    }))
    const { updateSettings } = await import('./api.js')
    await updateSettings({ ai_base_url: 'http://ollama.internal:11434', ai_vision_model: 'moondream' })

    expect(calls).toHaveLength(1)
    expect(calls[0].url).toMatch(/\/settings$/)
    expect(calls[0].opts.method).toBe('PUT')
    const body = JSON.parse(calls[0].opts.body)
    // The whole point: the field is present AND carries the typed value.
    expect(body).toHaveProperty('ai_vision_model', 'moondream')
    expect(body).toHaveProperty('ai_base_url', 'http://ollama.internal:11434')
  })

  it('surfaces a rejected save as an error instead of resolving quietly', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
      ok: false, status: 403, statusText: 'Forbidden',
      json: () => Promise.resolve({ detail: 'admin (owner) access required' }),
    })))
    const { updateSettings } = await import('./api.js')
    await expect(updateSettings({ ai_vision_model: 'moondream' }))
      .rejects.toThrow(/admin \(owner\) access required/)
  })

  it('lets a 403 from GET /ai/providers reach the caller — it is the read-only signal', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
      ok: false, status: 403, statusText: 'Forbidden',
      json: () => Promise.resolve({ detail: 'admin (owner) access required' }),
    })))
    const { getAiProviders } = await import('./api.js')
    // Previously this resolved to { providers: [] }, which the panel could not tell apart
    // from "you are an admin and no providers are configured".
    await expect(getAiProviders()).rejects.toThrow(/owner/i)
  })
})

describe('the endpoint form never misreports what the server holds', () => {
  const src = () => read('Settings.jsx')

  it('builds the PUT payload from both fields', () => {
    const s = src()
    const call = s.slice(s.indexOf('const saveEndpoint'), s.indexOf('const saveEndpoint') + 1200)
    expect(call).toMatch(/ai_base_url:\s*aiUrl\.trim\(\)/)
    expect(call).toMatch(/ai_vision_model:\s*aiVision\.trim\(\)/)
  })

  it('restores the server values when the save is rejected', () => {
    const s = src()
    const fail = s.slice(s.indexOf('const saveEndpoint'), s.indexOf('const saveEndpoint') + 1600)
    const rejected = fail.slice(fail.indexOf('.catch'))
    expect(rejected).toMatch(/setAiVision\(settings\.ai_vision_model/)
    expect(rejected).toMatch(/setAiUrl\(settings\.ai_base_url/)
    expect(rejected).toMatch(/not saved/i)
  })

  it('reports what the server kept when a 200 disagrees with what was sent', () => {
    const s = src()
    const ok = s.slice(s.indexOf('const saveEndpoint'), s.indexOf('const saveEndpoint') + 1600)
    expect(ok).toMatch(/drift/)
    expect(ok).toMatch(/was not applied/)
  })

  it('shows the outcome beside the Apply button, not only at the foot of the panel', () => {
    const s = src()
    const apply = s.indexOf('onClick={saveEndpoint}')
    const providers = s.indexOf('<AIProvidersPanel')
    const status = s.indexOf('aria-live="polite"', apply)
    expect(apply).toBeGreaterThan(-1)
    expect(status).toBeGreaterThan(apply)
    expect(status).toBeLessThan(providers)   // above the providers section, still in view
  })
})

describe('a user who cannot save is not offered an editable form', () => {
  it('disables the endpoint fields and Apply when the API says read-only', () => {
    const s = read('Settings.jsx')
    expect(s).toMatch(/const \[canEdit, setCanEdit\] = useState\(true\)/)
    expect(s).toMatch(/<AIProvidersPanel onAccess=\{setCanEdit\}/)
    // every control in the AI-endpoint block honours it
    expect(s).toMatch(/value=\{aiVision\}[\s\S]{0,160}disabled=\{busy \|\| !canEdit\}/)
    expect(s).toMatch(/value=\{aiUrl\}[\s\S]{0,160}disabled=\{busy \|\| !canEdit\}/)
    expect(s).toMatch(/onClick=\{saveEndpoint\} disabled=\{busy \|\| !canEdit\}/)
  })

  it('treats a 403 on /ai/providers as the read-only signal and says so', () => {
    const s = read('Settings.jsx')
    expect(s).toMatch(/403\\b\|forbidden\|owner/i)
    expect(s).toMatch(/setDenied\(forbidden\)/)
    expect(s).toMatch(/onAccess\?\.\(!forbidden\)/)
    expect(s).toMatch(/ReadOnlyNotice/)
    expect(s).toMatch(/owner-only/i)
    // and the swallow-everything catch is gone from the provider fetch
    expect(read('api.js')).not.toMatch(/\/ai\/providers`,\s*\{ headers: headers\(\) \}\)\.then\(j\)\.catch/)
  })

  it('gates the other owner-only writes in the panel too', () => {
    const s = read('Settings.jsx')
    expect(s).toMatch(/onChange=\{toggle\} disabled=\{busy \|\| !canEdit\}/)
    expect(s).toMatch(/onChange=\{toggleAutoApply\} disabled=\{busy \|\| !canEdit\}/)
    expect(s).toMatch(/onClick=\{saveFolder\}[\s\S]{0,120}!canEdit/)
  })
})

// ── Detaching a burst GPU (2026-07-29) ────────────────────────────────────────────
// Clearing the base URL but not the vision model left a GPU-only model name pinned in the
// override, and the panel showed nothing but vision_available:false. Both halves are asserted
// here: the panel must SAY why, and clearing must be one action instead of two fields.
describe('the panel explains a dead vision model and can undo the pin in one action', () => {
  const src = () => read('Settings.jsx')

  it('surfaces WHY vision is unavailable, next to the field that fixes it', () => {
    const s = src()
    expect(s).toMatch(/aiStatus\.vision_unavailable_reason/)
    // gated on the server's own verdict, not inferred in the SPA
    expect(s).toMatch(/!aiStatus\.vision_available/)
    // and it sits above the providers section, beside the Vision model input
    const reason = s.indexOf('vision_unavailable_reason}')
    expect(reason).toBeGreaterThan(s.indexOf('onClick={saveEndpoint}'))
    expect(reason).toBeLessThan(s.indexOf('<AIProvidersPanel'))
  })

  it('re-reads /ai/status after an apply, since clearing the override changes the answer', () => {
    const s = src()
    const body = s.slice(s.indexOf('const saveEndpoint'), s.indexOf('const useDeployDefault'))
    expect(body).toMatch(/return loadAiStatus\(\)/)
  })

  it('detaching a burst GPU clears BOTH fields in one action', () => {
    const s = src()
    expect(s).toMatch(/const useDeployDefault = \(\) => saveEndpoint\(\{ clearBoth: true \}\)/)
    const clear = s.slice(s.indexOf('const saveEndpoint'), s.indexOf('const useDeployDefault'))
    // both keys blanked together — clearing only one is the bug this exists for
    expect(clear).toMatch(/ai_base_url: '',\s*ai_vision_model: ''/)
    expect(s).toMatch(/Use deploy default \(clears both\)/)
  })

  it('a click event cannot be mistaken for a request to clear the fields', () => {
    const s = src()
    // onClick={saveEndpoint} passes a MouseEvent as the first argument; the clear path must be
    // opt-in by property, not by "did I get an argument at all".
    expect(s).toMatch(/const clearBoth = opts\?\.clearBoth === true/)
    expect(s).toMatch(/onClick=\{saveEndpoint\}/)
  })
})

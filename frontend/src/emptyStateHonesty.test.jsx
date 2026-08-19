import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// #378 item 3 — empty-state honesty. When the local model produced nothing AND no escalation happened,
// the manual-authoring state must say WHY it is manual and link an admin to Settings → AI Providers.
// The reason now comes from /ai/status's non-admin cloud signal (cloud_enabled / cloud_provider) —
// #378's first-class "is a governed cloud fallback enabled?" answer — instead of the AI-provenance
// zone the card previously used as a proxy.

const h = vi.hoisted(() => ({ status: { cloud_enabled: false, cloud_provider: null, cloud_zone: null } }))

vi.mock('./api.js', () => ({
  // Local model returns nothing usable → the card's draft fails, which is the empty state.
  suggestFix: () => Promise.resolve({ suggestion: '', is_template: false }),
  getFileRemediationDiffs: () => Promise.resolve([]),
  aiProvenance: () => ({ zone: 'local', provider: 'ollama', model: 'm', vision_model: 'v', host: 'localhost' }),
  getFileThumbnail: () => Promise.resolve(null),
  getFilePage: () => Promise.resolve(null),
  getFileGeometry: () => Promise.resolve(null),
  getScanAiCalls: () => Promise.resolve([]),      // no cloud call in the ledger → no escalation
  validateAlt: () => Promise.resolve({}),
}))
// The card reads /ai/status through aiModel.loadAiModels (module-cached in the real app). Control it
// here so cloud_enabled true vs false is exercised directly.
vi.mock('./aiModel.js', () => ({ loadAiModels: () => Promise.resolve(h.status) }))

const { default: EvidenceCard } = await import('./EvidenceCard.jsx')

// A single 1.1.1 image finding with no proposal and no evidence → the single-value editor, which
// auto-drafts on mount; the mocked local model returns nothing, so the draft fails.
const item = {
  id: 1, scan_id: 's1', file: 'flyer.pdf', rule_id: '1.1.1', rule_name: 'Non-text Content',
  status: 'pending', finding_count: 1,
}

const mount = async (props = {}) => {
  const { container: c, root } = createTestRoot()
  await act(async () => { root.render(createElement(EvidenceCard, { item, onAct: () => {}, ...props })) })
  // let the auto-draft promise AND the follow-on /ai/status fetch settle
  for (let k = 0; k < 6; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
  return c
}
beforeEach(() => { h.status = { cloud_enabled: false, cloud_provider: null, cloud_zone: null } })
afterEach(unmountAll)

describe('EvidenceCard — empty-state honesty from /ai/status (#378 item 3)', () => {
  it('cloud_enabled=false: explains it is manual and links to Settings → AI Providers', async () => {
    const c = await mount()
    const hint = c.querySelector('.evcard-manual-empty')
    expect(hint).not.toBeNull()
    expect(hint.textContent).toMatch(/why you.?re writing this by hand/i)
    expect(hint.textContent).toMatch(/no governed cloud provider is enabled/i)
    const link = [...hint.querySelectorAll('button')].find((b) => /Settings → AI Providers/.test(b.textContent))
    expect(link).toBeTruthy()
  })

  it('the Settings link dispatches the app’s existing open-settings event (no hardcoded URL)', async () => {
    const c = await mount()
    const link = [...c.querySelectorAll('.evcard-manual-empty button')]
      .find((b) => /Settings → AI Providers/.test(b.textContent))
    let fired = null
    const onOpen = (e) => { fired = e }
    window.addEventListener('acp:open-settings', onOpen)
    await act(async () => { link.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    window.removeEventListener('acp:open-settings', onOpen)
    expect(fired).not.toBeNull()
    expect(fired.detail?.section).toBe('ai-providers')
  })

  it('cloud_enabled=true: names the provider it would escalate to, not "none enabled"', async () => {
    h.status = { cloud_enabled: true, cloud_provider: 'openai', cloud_zone: 'customer_cloud' }
    const c = await mount()
    const hint = c.querySelector('.evcard-manual-empty')
    expect(hint).not.toBeNull()
    expect(hint.textContent).toMatch(/openai/)
    // With a provider enabled, the honest message must NOT claim none is enabled.
    expect(hint.textContent).not.toMatch(/no governed cloud provider is enabled/i)
    expect(hint.textContent).toMatch(/couldn.?t ground a description/i)
    // Still offers the admin the Settings entry point.
    const link = [...hint.querySelectorAll('button')].find((b) => /Settings → AI Providers/.test(b.textContent))
    expect(link).toBeTruthy()
  })
})

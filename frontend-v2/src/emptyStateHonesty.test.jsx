import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// P1 item 3 — empty-state honesty. When the local model produced nothing AND no governed cloud
// provider is enabled to fall back to, the manual-authoring state must say WHY it is manual (not a
// raw "Ollama not running") and link an admin to Settings → AI Providers, reusing the app's existing
// navigation rather than hardcoding a URL.

const h = vi.hoisted(() => ({ zone: 'local' }))

vi.mock('./api.js', () => ({
  // Local model returns nothing usable → the card's draft fails, which is the empty state.
  suggestFix: () => Promise.resolve({ suggestion: '', is_template: false }),
  getFileRemediationDiffs: () => Promise.resolve([]),
  aiProvenance: () => ({ zone: h.zone, provider: 'ollama', model: 'm', vision_model: 'v', host: 'localhost' }),
  getFileThumbnail: () => Promise.resolve(null),
  getFilePage: () => Promise.resolve(null),
  getFileGeometry: () => Promise.resolve(null),
  getScanAiCalls: () => Promise.resolve([]),      // no cloud call in the ledger → no escalation
  validateAlt: () => Promise.resolve({}),
}))

const { default: EvidenceCard } = await import('./EvidenceCard.jsx')

// A single 1.1.1 image finding with no proposal and no evidence → the single-value editor, which
// auto-drafts on mount; the mocked local model returns nothing, so the draft fails.
const item = {
  id: 1, scan_id: 's1', file: 'flyer.pdf', rule_id: '1.1.1', rule_name: 'Non-text Content',
  status: 'pending', finding_count: 1,
}

let container
const mount = async (props = {}) => {
  const { container: c, root } = createTestRoot()
  container = c
  await act(async () => { root.render(createElement(EvidenceCard, { item, onAct: () => {}, ...props })) })
  // let the auto-draft promise settle
  await act(async () => { await Promise.resolve() })
  return c
}
beforeEach(() => { h.zone = 'local' })
afterEach(unmountAll)

describe('EvidenceCard — empty-state honesty when there is no cloud fallback', () => {
  it('explains WHY it is manual and links to Settings → AI Providers (local-only, draft failed)', async () => {
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

  it('does NOT show the enable-cloud hint when a cloud provider is already the active zone', async () => {
    h.zone = 'cloud'         // cloud is enabled/active — the honest message is not "enable one"
    const c = await mount()
    expect(c.querySelector('.evcard-manual-empty')).toBeNull()
  })
})

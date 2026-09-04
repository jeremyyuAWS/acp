import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// #378 item 2 — the review card renders the escalation path from the REAL /ai/suggest response field,
// not from the ai_calls ledger. A single 1.1.1 finding with no draft auto-drafts on mount; the mocked
// backend returns a draft that escalated to a cloud provider (provider / processing_zone / escalation
// steps). The card must show "escalated to {provider}" WITHOUT any ledger — getScanAiCalls returns []
// here, so a rendered path can only have come from the draft response.

const suggestFix = vi.fn()
vi.mock('./api.js', () => ({
  suggestFix: (...a) => suggestFix(...a),
  getFileRemediationDiffs: () => Promise.resolve([]),
  aiProvenance: () => ({ zone: 'local', provider: 'ollama', model: 'm', vision_model: 'v', host: 'localhost' }),
  getFileThumbnail: () => Promise.resolve(null),
  getFilePage: () => Promise.resolve(null),
  getFileGeometry: () => Promise.resolve(null),
  getSourceLink: () => Promise.resolve({ url: null }),
  getScanAiCalls: () => Promise.resolve([]),      // NO ledger — a path can only come from the response
  validateAlt: () => Promise.resolve({}),
}))

const { default: EvidenceCard } = await import('./EvidenceCard.jsx')
const { resetAutoDraftBreaker } = await import('./autoDraft.js')

const item = { id: 1, scan_id: 's1', file: 'flyer.pdf', rule_id: '1.1.1',
               rule_name: 'Non-text Content', status: 'pending', finding_count: 1 }

const mount = async () => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(EvidenceCard, { item, onAct: () => {} })) })
  return container
}
const settle = async (n = 6) => {
  for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}

beforeEach(() => { suggestFix.mockReset(); resetAutoDraftBreaker() })
afterEach(unmountAll)

describe('EvidenceCard — escalation path from the draft response (#378 item 2)', () => {
  it('renders the numbered path from the response field, with no ledger involved', async () => {
    suggestFix.mockResolvedValue({
      suggestion: 'A bar chart of Q3 revenue by region', is_template: false, model: 'gpt-4o',
      provider: 'openai', processing_zone: 'customer_cloud', cost_usd: 0.0021,
      escalation: [
        { provider: 'ollama', zone: 'local', outcome: 'no grounded description' },
        { provider: 'openai', zone: 'customer_cloud', outcome: 'produced a description', cost_usd: 0.0021 },
      ],
    })
    const c = await mount(); await settle()
    const path = c.querySelector('.evcard-escalation')
    expect(path).not.toBeNull()
    const t = path.textContent
    expect(t).toContain('local attempted')
    expect(t).toContain('no grounded description')
    expect(t).toContain('escalated to openai')
    expect(t).toContain('(gpt-4o)')      // the cloud model, from the response's own field
    expect(t).toContain('grounded')
    // On the surface, not behind the audit disclosure.
    expect(path.closest('details.evcard-details')).toBeNull()
  })

  it('shows no path for a plain local draft (response carries no escalation field)', async () => {
    suggestFix.mockResolvedValue({
      suggestion: 'A stethoscope on a desk', is_template: false, model: 'llava:7b',
      provider: 'ollama', processing_zone: 'local',
    })
    const c = await mount(); await settle()
    expect(c.querySelector('.evcard-escalation')).toBeNull()
  })
})

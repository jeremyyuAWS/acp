import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// W6 — AI provenance must be visible ON THE CARD SURFACE, not only behind the audit disclosure,
// and it must show the ACTUAL zone the file's AI ran in (from the per-call ledger), not the
// configured provider. The whole risk this guards is a silent GPU→CPU fallback: config says
// "cloud", the call really ran "local", and a reviewer approving the weaker output must see the
// truth. `actualZone` (passed by Remediate from getScanAiCalls) therefore WINS over the configured
// aiProvenance().zone, and when neither is known no badge is fabricated.

const h = vi.hoisted(() => ({ prov: null }))

vi.mock('./api.js', () => ({
  suggestFix: () => Promise.resolve({ suggestion: '', is_template: false }),
  getFileRemediationDiffs: () => Promise.resolve([]),
  aiProvenance: () => h.prov,
  getFileThumbnail: () => Promise.resolve(null),
  getFilePage: () => Promise.resolve(null),
  getFileGeometry: () => Promise.resolve(null),
  getScanAiCalls: () => Promise.resolve([]),
  validateAlt: () => Promise.resolve({}),
}))

afterEach(unmountAll)
beforeEach(() => { h.prov = null })

const { default: EvidenceCard } = await import('./EvidenceCard.jsx')

// A proposal is present, so AI produced a value → provenance is meaningful.
const item = {
  id: 1, scan_id: 's1', file: 'report.docx', rule_id: '2.4.6', rule_name: 'Headings and Labels',
  status: 'pending', finding_count: 1,
  proposals: [{ locator: 'w:body#h1', before: 'Section 1', proposed_value: 'Q3 revenue by region',
                rationale: 'grounded in the section’s opening sentence' }],
}

let container
const mount = async (props = {}) => {
  const { container: c, root } = createTestRoot()
  container = c
  await act(async () => { root.render(createElement(EvidenceCard, { item, onAct: () => {}, ...props })) })
}

describe('EvidenceCard — W6 provenance on the surface', () => {
  it('shows the real zone as a chip on the card surface, NOT behind the audit disclosure', async () => {
    await mount({ actualZone: 'cloud' })
    const chip = container.querySelector('.evcard-prov-surface')
    expect(chip).not.toBeNull()
    expect(chip.textContent).toContain('🟡 Cloud AI')
    expect(chip.closest('details.evcard-details')).toBeNull()   // surfaced, not buried
  })

  it('shows 🟢 Local AI for a local zone', async () => {
    await mount({ actualZone: 'local' })
    expect(container.querySelector('.evcard-prov-surface').textContent).toContain('🟢 Local AI')
  })

  it('the ACTUAL zone wins over the configured provider zone (the silent-fallback case)', async () => {
    h.prov = { zone: 'cloud', provider: 'runpod', model: 'm', vision_model: 'v', host: 'runpod' }
    await mount({ actualZone: 'local' })
    const chip = container.querySelector('.evcard-prov-surface')
    expect(chip.textContent).toContain('🟢 Local AI')      // real local beats configured cloud
    expect(chip.textContent).not.toContain('(configured)') // it is a real, per-call zone
  })

  it('falls back to the configured zone (labelled) only when the real zone is unknown', async () => {
    h.prov = { zone: 'local', provider: 'ollama', model: 'm', vision_model: 'v', host: 'localhost' }
    await mount({})                                         // no actualZone passed
    const chip = container.querySelector('.evcard-prov-surface')
    expect(chip).not.toBeNull()
    expect(chip.textContent).toContain('🟢 Local AI')
    expect(chip.textContent).toContain('(configured)')     // honestly marked as intent, not fact
  })

  it('fabricates no badge when neither a real nor a configured zone is known', async () => {
    h.prov = null
    await mount({})
    expect(container.querySelector('.evcard-prov-surface')).toBeNull()
  })
})

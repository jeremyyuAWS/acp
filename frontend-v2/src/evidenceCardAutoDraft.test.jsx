import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// Auto-generate the preview (AI Work Inbox): a value-fix that reaches the inbox with no draft must
// generate its AI suggestion on its own — the reviewer never clicks "Draft with AI". These pin the
// automatic firing, the once-only guard, and the do-no-harm rules (never overwrite the reviewer's
// text; never fire when a proposal is already present).

// Unmount every root this file mounts — see testRoots.js.
afterEach(unmountAll)

const suggestFix = vi.fn()
vi.mock('./api.js', () => ({
  suggestFix: (...a) => suggestFix(...a),
  getFileRemediationDiffs: () => Promise.resolve([]),
  aiProvenance: () => null,
  getFileThumbnail: () => Promise.resolve(null),
  getFilePage: () => Promise.resolve(null),
  getFileGeometry: () => Promise.resolve(null),
  getScanAiCalls: () => Promise.resolve([]),
  validateAlt: () => Promise.resolve({}),
}))

const { default: EvidenceCard } = await import('./EvidenceCard.jsx')

const base = { id: 1, scan_id: 's1', file: 'handbook.pdf', rule_id: '1.1.1',
               rule_name: 'Non-text Content', status: 'pending', finding_count: 1 }

let container, root
const mount = async (item) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(EvidenceCard, { item, onAct: () => {} })) })
}
const settle = async (n = 6) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const inputs = () => [...container.querySelectorAll('.evcard-rec-input')]

beforeEach(() => {
  suggestFix.mockReset()
  suggestFix.mockResolvedValue({ suggestion: 'A clinician reviews a chart.', is_template: false, model: 'llava:7b' })
})

describe('EvidenceCard — auto-generate the preview', () => {
  it('drafts automatically on mount, with no button click', async () => {
    await mount({ ...base }); await settle()
    expect(suggestFix).toHaveBeenCalledWith('s1', 'handbook.pdf', '1.1.1', undefined)
    expect(inputs()[0].value).toBe('A clinician reviews a chart.')
    // the manual button is gone
    expect(container.querySelector('.evcard-draft-btn')).toBeNull()
  })

  it('does NOT auto-draft when a server proposal is already present', async () => {
    await mount({ ...base, proposals: [{ locator: 'p1', proposed_value: 'Existing draft.', rationale: 'vision' }] })
    await settle()
    expect(suggestFix).not.toHaveBeenCalled()
  })

  it('does NOT auto-draft a judgement criterion with nothing to type', async () => {
    await mount({ ...base, rule_id: '1.4.3', rule_name: 'Contrast (Minimum)' }); await settle()
    expect(suggestFix).not.toHaveBeenCalled()
  })

  it('fires at most once even across re-renders', async () => {
    await mount({ ...base }); await settle()
    await act(async () => { root.render(createElement(EvidenceCard, { item: { ...base }, onAct: () => {} })) })
    await settle()
    expect(suggestFix).toHaveBeenCalledTimes(1)
  })
})

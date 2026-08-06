// WCAG-exception toggles (HITL-six close-out) — the reviewer resolves a finding a model must not
// decide by applying the standard's own exception: a decorative image needs no description (1.1.1),
// an essential logo/brand mark is exempt from images-of-text (1.4.5/1.4.9). One tap → an approval
// carrying a `resolution`, and NO written value (nothing is misrepresented as an authored fix).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

vi.mock('./api.js', () => ({
  suggestFix: vi.fn(),
  getFileRemediationDiffs: () => Promise.resolve([]),
  aiProvenance: () => null,
  getFileThumbnail: () => Promise.resolve(null),
  getFilePage: () => Promise.resolve(null),
  getFileGeometry: () => Promise.resolve(null),
  getScanAiCalls: () => Promise.resolve([]),
  validateAlt: () => Promise.resolve({}),
}))

// Unmount every root this file mounts — see testRoots.js.
afterEach(unmountAll)

const { default: EvidenceCard } = await import('./EvidenceCard.jsx')

const PNG = 'data:image/png;base64,iVBORw0KGgo='
const imageItem = (rule_id) => ({
  id: 3, scan_id: 's1', file: 'deck.pptx', rule_id, rule_name: 'Non-text Content',
  status: 'pending', finding_count: 1,
  evidence: [{ locator: 'ppt/slides/slide1.xml#rId2', thumb: PNG }],
})
// An images-of-text finding whose detected KIND is known (from the model's own words, #130) — the
// signal that routes the exemption affordance. `desc` seeds describedImageType via proposed_value.
const describedItem = (rule_id, desc) => ({
  id: 4, scan_id: 's1', file: 'sheet.xlsx', rule_id, rule_name: 'Images of Text',
  status: 'pending', finding_count: 1,
  proposals: [{ locator: 'image 1', proposed_value: desc, thumb: PNG }],
})

let container, root, onAct
const mount = async (item) => {
  onAct = vi.fn().mockResolvedValue(undefined)
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(EvidenceCard, { item, onAct, editable: true })) })
}
const btnWith = (text) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(text))
const click = async (text) => {
  await act(async () => { btnWith(text).dispatchEvent(new MouseEvent('click', { bubbles: true })) })
}

beforeEach(() => { document.body.innerHTML = '' })

describe('EvidenceCard — WCAG-exception toggles', () => {
  it('offers Decorative on a 1.1.1 image finding, not Essential', async () => {
    await mount(imageItem('1.1.1'))
    expect(btnWith('Decorative')).toBeTruthy()
    expect(btnWith('Essential')).toBeFalsy()
  })

  it('offers Essential on a 1.4.5 images-of-text finding, not Decorative', async () => {
    await mount(imageItem('1.4.5'))
    expect(btnWith('Essential')).toBeTruthy()
    expect(btnWith('Decorative')).toBeFalsy()
  })

  it('also offers Essential on 1.4.9 (Images of Text, No Exception path)', async () => {
    await mount(imageItem('1.4.9'))
    expect(btnWith('Essential')).toBeTruthy()
  })

  it('marking decorative approves with resolution and NO written value', async () => {
    await mount(imageItem('1.1.1'))
    await click('Decorative')
    const [, status, , finalValue, opts] = onAct.mock.calls[0]
    expect(status).toBe('approved')
    expect(opts.resolution).toBe('decorative')
    expect(opts.approvedValues).toBeNull()   // an exception writes nothing into the document
    expect(finalValue).toBeNull()
  })

  it('marking essential approves with the logo/brand exemption', async () => {
    await mount(imageItem('1.4.5'))
    await click('Essential')
    const [, status, , , opts] = onAct.mock.calls[0]
    expect(status).toBe('approved')
    expect(opts.resolution).toBe('essential_exception')
    expect(opts.approvedValues).toBeNull()
  })

  it('a CHART on 1.4.9 gets no logo/exempt question — a chart is not a logo (#130 routing)', async () => {
    await mount(describedItem('1.4.9', 'Bar chart of quarterly revenue: Q1 10, Q2 20, Q3 30'))
    expect(btnWith('Essential')).toBeFalsy()
    expect(container.querySelector('.evcard-exception-note').textContent).toMatch(/not a logo/i)
  })

  it('a LOGO on 1.4.9 keeps the essential-logotype exemption', async () => {
    await mount(describedItem('1.4.9', 'Company logo — the Acme wordmark in blue'))
    expect(btnWith('Essential')).toBeTruthy()
  })

  it('a normal approve still writes the value and carries no resolution', async () => {
    await mount(imageItem('1.1.1'))
    await click('Approve')
    const [, status, , , opts] = onAct.mock.calls[0]
    expect(status).toBe('approved')
    expect(opts.resolution ?? null).toBeNull()
    expect(opts.approvedValues).not.toBeNull()   // the per-image path still runs
  })
})

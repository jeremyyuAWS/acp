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
  getSourceLink: () => Promise.resolve({ url: null }),
  getScanAiCalls: () => Promise.resolve([]),
  validateAlt: () => Promise.resolve({}),
}))

// Unmount every root this file mounts — see testRoots.js.
afterEach(unmountAll)

const { default: EvidenceCard } = await import('./EvidenceCard.jsx')

const PNG = 'data:image/png;base64,iVBORw0KGgo='
// The OCR transcript the card arrives pre-filled with, and a real description of the same picture.
// Kept distinct on purpose: the whole point of the describe lane is that these are different kinds
// of text, and a test that used one string for both would prove nothing.
const DRAFT = 'Bar chart of quarterly revenue: Q1 10, Q2 20, Q3 30'
const OWN_WORDS = 'A bar chart comparing quarterly revenue, rising steadily from Q1 to Q3.'
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
// Type into the first per-image editor, the way a reviewer would. React tracks the DOM value
// internally, so setting .value alone is not observed — go through the native setter.
const type = async (text) => {
  const box = container.querySelector('textarea, input[type="text"]')
  const proto = box instanceof window.HTMLTextAreaElement
    ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(box, text)
  await act(async () => { box.dispatchEvent(new Event('input', { bubbles: true })) })
}
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

  // ── ADR 0055: the way out of the chart dead end ────────────────────────────────────────────
  //
  // The test above ("a CHART gets no logo/exempt question") was correct and incomplete: it left a
  // chart with guidance and NOTHING TO CLICK. Replacing a chart with its axis labels destroys the
  // data, so the reviewer who must keep the picture now describes it instead — resolving 1.4.5 by
  // judgement while the description is written as 1.1.1 alt text and verified before certification.

  it('a CHART now gets a describe action alongside the guidance, and still no logo question', async () => {
    await mount(describedItem('1.4.9', 'Bar chart of quarterly revenue: Q1 10, Q2 20, Q3 30'))
    expect(btnWith('Essential')).toBeFalsy()
    expect(container.querySelector('.evcard-exception-note').textContent).toMatch(/not a logo/i)
    expect(btnWith('describe it')).toBeTruthy()
  })

  it('the describe button is DISABLED while the box still holds the OCR draft', async () => {
    // THE TRAP THIS GUARDS, found by writing the test rather than by reading the code: the editor
    // is seeded from proposed_value, and on a 1.4.5 card that draft is the TRANSCRIPT — the words
    // baked into the picture. Clicking straight through would file the picture's own text as its
    // description. The button therefore waits for the reviewer's OWN words, not merely for the box
    // to be non-empty.
    await mount(describedItem('1.4.9', DRAFT))
    const btn = btnWith('describe it')
    expect(btn).toBeTruthy()
    expect(btn.disabled).toBe(true)
    expect(btn.title).toMatch(/not a description of it/i)
  })

  it('describing SENDS the reviewer text — the one resolution that is not value-free', async () => {
    // Every other resolution suppresses approvedValues, and must: approving "Mark as decorative"
    // once wrote the card's own UI label into the document (#43). This one carries content by
    // design, so the suppression has to know the difference — if it does not, the reviewer's work
    // reaches nothing and the route rejects the decision.
    await mount(describedItem('1.4.5', DRAFT))
    await type(OWN_WORDS)
    const btn = btnWith('describe it')
    expect(btn.disabled).toBe(false)           // the reviewer's own words unlock it
    await click('describe it')
    const [, status, note, finalValue, opts] = onAct.mock.calls[0]
    expect(status).toBe('approved')
    expect(opts.resolution).toBe('described_not_replaced')
    expect(opts.approvedValues).not.toBeNull()
    expect(opts.approvedValues).toContain(OWN_WORDS)
    expect(opts.approvedValues).not.toContain(DRAFT)   // the transcript is NOT what was filed
    expect(finalValue).toBeTruthy()            // the audit line carries what was authored
    expect(note).toMatch(/described/i)         // and self-describes when the reviewer left it blank
  })

  it('a LOGO is offered the exemption, not the describe action — the standard has a real answer there', async () => {
    await mount(describedItem('1.4.9', 'Company logo — the Acme wordmark in blue'))
    expect(btnWith('Essential')).toBeTruthy()
    expect(btnWith('describe it')).toBeFalsy()
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

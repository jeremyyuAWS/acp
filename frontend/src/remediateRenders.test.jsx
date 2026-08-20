import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import RemediationWork from './RemediationWork.jsx'
import ManualWork from './ManualWork.jsx'
import RemediationVerify from './RemediationVerify.jsx'
import CloseoutPanel from './CloseoutPanel.jsx'
import { CAPABILITY_FALLBACK, ASSESSMENT_FALLBACK } from './capability.js'

// Do the mounted panels actually PRODUCE something for a realistic run?
//
// remediateWiring.test.jsx proves they are mounted and receive the right props. It cannot prove
// they render, and that distinction is the whole risk here: every one of these components returns
// `null` when it cannot measure anything, so a shape mismatch between what Remediate passes and
// what the component expects produces a blank panel, a green suite, and a screen that looks like
// the feature was never built.
//
// This drives the REAL capability tables — CAPABILITY_FALLBACK and ASSESSMENT_FALLBACK, the exact
// objects App holds and passes down — against files shaped like scan rows, and asserts text comes
// out. It is the check that has to pass before the old Remediate screen can be retired, because
// until it does, "the new panels work" is an assumption.

const cap = CAPABILITY_FALLBACK
const assessment = ASSESSMENT_FALLBACK

// Two documents, opened and scored, carrying findings across all three lanes:
//   1.3.1 on docx  → auto      (deterministic; the batch)
//   1.1.1 on docx  → assisted  (AI drafts, a person approves)
//   2.1.2 on docx  → human     (only a person can do it)
const FILES = [
  {
    file: 'policies/handbook.docx', name: 'handbook.docx', status: 'done', score: 62,
    issues: [
      { sc: '1.3.1', severity: 'SERIOUS', message: 'Headings skip a level' },
      { sc: '1.1.1', severity: 'CRITICAL', message: 'Image has no alt text' },
      { sc: '2.1.2', severity: 'SERIOUS', message: 'Keyboard trap' },
    ],
  },
  {
    file: 'policies/onboarding.docx', name: 'onboarding.docx', status: 'done', score: 88,
    issues: [{ sc: '1.3.1', severity: 'MODERATE', message: 'Table has no header row' }],
  },
]

const text = (node) => renderToStaticMarkup(node)
  .replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&')
  .replace(/&quot;/g, '"').replace(/\s+/g, ' ').trim()

describe('the board panels render for a realistic run', () => {
  it('RemediationWork (R2/R3) produces content, not an empty panel', () => {
    const t = text(createElement(RemediationWork, { files: FILES, cap, assessment }))
    expect(t.length, 'panel rendered something').toBeGreaterThan(40)
    // It must divide the work rather than print one total — the lanes are the point.
    expect(t).toMatch(/\d/)
  })

  it('ManualWork (R6) produces content when a human-lane finding exists', () => {
    // 2.1.2 on docx is `human` in the real table. If this renders nothing, either the lane
    // derivation or the prop shape is wrong.
    const t = text(createElement(ManualWork, { files: FILES, cap, assessment }))
    expect(t.length).toBeGreaterThan(20)
  })

  it('RemediationVerify (R9) produces content', () => {
    const t = text(createElement(RemediationVerify, { files: FILES, cap, assessment }))
    expect(t.length).toBeGreaterThan(20)
  })

  it('CloseoutPanel (R12) produces content', () => {
    const t = text(createElement(CloseoutPanel, { docs: FILES }))
    expect(t.length).toBeGreaterThan(20)
  })
})

// Documents discovery listed and Assess never opened. No score, no issues, status 'error'.
const UNASSESSED = [
  { file: 'a.docx', name: 'a.docx', status: 'error' },
  { file: 'b.docx', name: 'b.docx', status: 'error' },
]

describe('an estate that was never assessed is not an estate with no findings', () => {
  // THE BUG THIS FOUND. Mounting these panels put a false all-clear on the Remediate page:
  // two unopened documents rendered "0 + 0 + 0 + 0 + 0 = 0 findings" and "the same 0 findings
  // the assessment counted", which reads as a clean bill of health for an estate nobody checked.
  //
  // ADR 0016 in another place: a discovered-but-unassessed document has NO findings, not zero
  // findings. The discriminator is whether any document was OPENED, never whether any finding
  // was found.

  it('RemediationWork renders nothing when no document was opened', () => {
    expect(text(createElement(RemediationWork, { files: UNASSESSED, cap, assessment }))).toBe('')
  })

  it('RemediationVerify renders nothing when no document was opened', () => {
    expect(text(createElement(RemediationVerify, { files: UNASSESSED, cap, assessment }))).toBe('')
  })

  it('ManualWork already said this honestly, and still does', () => {
    // It never printed a zero grid — it states the fact in words. Asserted so the good behaviour
    // is pinned rather than assumed, and because my first version of this test wrongly expected
    // it to render nothing at all.
    const t = text(createElement(ManualWork, { files: UNASSESSED, cap, assessment }))
    expect(t).toMatch(/manual lane/i)
    expect(t).not.toMatch(/\b0 \+ 0\b/)
  })
})

describe('but a genuinely EMPTY estate may still report zeros', () => {
  // The distinction the existing suite already encodes ("distinguishes that from a real run over
  // an empty estate"), and which the first version of my fix flattened. Zero files discovered
  // honestly means zero findings; saying so is a measurement, not a claim about unchecked work.
  it('RemediationWork renders for a real run over zero files', () => {
    expect(text(createElement(RemediationWork, { files: [], cap, assessment })).length)
      .toBeGreaterThan(40)
  })
})

describe('the capability tables Remediate is actually given are the ones these expect', () => {
  it('CAPABILITY_FALLBACK is keyed format → criterion → lane', () => {
    // The shape assumption behind every panel above. A change here blanks all of them at once,
    // silently, which is exactly how ten components sat unmounted without anyone noticing.
    expect(cap).toBeTruthy()
    expect(cap.docx).toBeTruthy()
    expect(['auto', 'assisted', 'human']).toContain(cap.docx['1.3.1'])
  })

  it('covers all three lanes, so a lane-splitting panel has something to split', () => {
    const lanes = new Set(Object.values(cap.docx))
    for (const lane of ['auto', 'assisted', 'human']) {
      expect(lanes.has(lane), `docx has at least one ${lane} criterion`).toBe(true)
    }
  })
})

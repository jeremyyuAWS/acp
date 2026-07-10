// Contract for the per-file remediation recommendation (sim.js recommendFor).
// The fixability split is now sourced from the ONE remediation-capability table
// (capability.js), the same source Assess + FileDrawer read — so a recommendation
// can't disagree with them. Regression guards:
//  - real backend findings carry wcag as '1.4.3 Contrast (Minimum)', not the SC_
//    form, and both must parse (the mislabel bug that classed files 'fully automatic');
//  - fixability is FORMAT-AWARE: a PDF's only mechanical fixes are language + title;
//    contrast is auto on docx/xlsx/html but human on pptx/pdf; alt text is assisted.
import { describe, it, expect } from 'vitest'
import { recommendFor } from './sim.js'

const mk = (type, wcags, extra = {}) => ({
  type, status: 'issues', compliant: false, ageDays: 30, views90d: 100, tags: [], skipped_rules: 0,
  issues: wcags.map((w) => ({ wcag: w, severity: 'SERIOUS' })), ...extra,
})

describe('recommendFor — remediation mode', () => {
  it('does NOT call a PDF with a contrast finding fully automatic (real wcag format)', () => {
    const f = mk('pdf', ['1.3.1 Info and Relationships', '2.4.2 Page Titled',
      '3.1.1 Language of Page', '1.4.3 Contrast (Minimum)', '1.4.6 Contrast (Enhanced)'])
    const r = recommendFor(f)
    expect(r.mode).toBe('assisted')
    expect(r.rationale).not.toMatch(/No human needed/)
  })

  it('calls a PDF with only language + title findings fully automatic', () => {
    const r = recommendFor(mk('pdf', ['3.1.1 Language of Page', '2.4.2 Page Titled']))
    expect(r.mode).toBe('auto')
  })

  it('escalates a PDF whose findings the PDF remediator cannot touch (structure)', () => {
    const r = recommendFor(mk('pdf', ['1.3.1 Info and Relationships']))
    expect(r.mode).toBe('assisted')
    expect(r.rationale).toMatch(/mechanically fixable in a PDF/i)
  })

  it('escalates a file with an alt-text finding — 1.1.1 is assisted (AI drafts, human approves), never silent auto', () => {
    const r = recommendFor(mk('html', ['1.1.1 Non-text Content', '2.4.2 Page Titled']))
    expect(r.mode).toBe('assisted')
  })

  it('still auto-fixes mechanical-only findings (titles, language, structure)', () => {
    const r = recommendFor(mk('html', ['2.4.2 Page Titled', '3.1.1 Language of Page', '1.3.1 Info and Relationships']))
    expect(r.mode).toBe('auto')
  })

  it('routes contrast to human review in the RECOMMENDATION on every format (policy)', () => {
    // Contrast is technically auto-fixable on docx (the capability says so, and Assess /
    // FileDrawer count it), but recolouring is a judgement call, so the recommended MODE
    // routes a human in regardless of format — docx (capability: auto) and pptx (human) alike.
    const d = recommendFor(mk('docx', ['1.4.3 Contrast (Minimum)', '2.4.2 Page Titled']))
    expect(d.mode).toBe('assisted')
    expect(d.rationale).toMatch(/contrast/i)
    expect(recommendFor(mk('pptx', ['1.4.3 Contrast (Minimum)', '2.4.2 Page Titled'])).mode).toBe('assisted')
    // A file with only non-contrast mechanical fixes is still fully automatic.
    expect(recommendFor(mk('docx', ['2.4.2 Page Titled', '1.3.1 Info and Relationships'])).mode).toBe('auto')
  })

  it('still recognizes the SC_-prefixed sim wcag format', () => {
    // pptx contrast (1.4.3) is human, so this both exercises SC_ parsing and stays assisted.
    expect(recommendFor(mk('pptx', ['SC_1_4_3'])).mode).toBe('assisted')
  })
})

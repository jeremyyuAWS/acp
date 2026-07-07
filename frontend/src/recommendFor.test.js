// Contract for the per-file remediation recommendation (sim.js recommendFor).
// Regression guard for the mislabel bug: real backend findings carry wcag as
// '1.4.3 Contrast (Minimum)', not the SC_-prefixed form the fixability sets used,
// so contrast/link/media files were silently classed 'fully automatic'. Also
// guards the format-awareness: a PDF's only mechanical fixes are language + title.
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

  it('escalates HTML contrast in the real wcag format (was silently auto before)', () => {
    const r = recommendFor(mk('html', ['1.4.3 Contrast (Minimum)', '1.1.1 Non-text Content']))
    expect(r.mode).toBe('assisted')
  })

  it('still auto-fixes mechanical-only HTML', () => {
    const r = recommendFor(mk('html', ['1.1.1 Non-text Content', '2.4.2 Page Titled', '3.1.1 Language of Page']))
    expect(r.mode).toBe('auto')
  })

  it('still recognizes the SC_-prefixed sim format', () => {
    expect(recommendFor(mk('html', ['SC_1_4_3'])).mode).toBe('assisted')
  })
})

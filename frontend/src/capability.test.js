import { describe, it, expect } from 'vitest'
import { CAPABILITY_FALLBACK, fmtOf, modeFor, isAuto, autoSCs, reviewRecommended, REVIEW_RECOMMENDED_SC } from './capability.js'

const CAP = CAPABILITY_FALLBACK

describe('remediation capability — format-aware single source of truth', () => {
  describe('fmtOf', () => {
    it('normalizes the explicit type field', () => {
      expect(fmtOf({ type: 'docx' })).toBe('docx')
      expect(fmtOf({ type: 'HTML' })).toBe('html')
      expect(fmtOf({ type: 'htm' })).toBe('html')
    })
    it('falls back to the file extension', () => {
      expect(fmtOf({ file: 'report.pdf' })).toBe('pdf')
      expect(fmtOf({ file: 'page.htm' })).toBe('html')
    })
    it('returns null for a format we do not map', () => {
      expect(fmtOf({ file: 'notes.txt' })).toBeNull()
      expect(fmtOf({})).toBeNull()
    })
  })

  describe('modeFor / isAuto — conservative default', () => {
    it('defaults any unknown (format, sc) to human, never a silent auto', () => {
      expect(modeFor(CAP, 'docx', '9.9.9')).toBe('human')
      expect(modeFor(CAP, 'nope', '1.1.1')).toBe('human')
      expect(isAuto(CAP, 'docx', '9.9.9')).toBe(false)
    })
  })

  describe('the original bug: docx IS auto-fixable (format-aware, not format-blind)', () => {
    it('reports real auto-fixable criteria for a docx', () => {
      // Proven by round-trip in tests/test_remediation_capability.py: includes 3.1.1 (language)
      // and 3.3.2 (form labels), which the earlier hand map / sparse table omitted.
      expect(autoSCs(CAP, 'docx')).toEqual(new Set(['1.3.1', '1.4.3', '2.4.2', '2.4.6', '3.1.1', '3.3.2']))
    })
    it('includes docx contrast (1.4.3), which the old hand map omitted', () => {
      expect(isAuto(CAP, 'docx', '1.4.3')).toBe(true)
    })
    it('treats docx language (3.1.1) as auto — the dc:language write clears it on re-scan', () => {
      // Corrected from the sparse version's "human (engine-blocked)": the round-trip proves
      // writing docProps/core.xml dc:language does clear docx 3.1.1.
      expect(isAuto(CAP, 'docx', '3.1.1')).toBe(true)
      expect(modeFor(CAP, 'docx', '3.1.1')).toBe('auto')
    })
  })

  describe('format-awareness: the same criterion differs by format', () => {
    it('contrast 1.4.3 is auto on every format (pdf gained a content-stream darkener)', () => {
      // pptx corrected from the sparse version's "human (not verified)": the recolour is now
      // round-trip verified. pdf joined when remediate_pdf grew the text-scoped darken
      // (_fix_pdf_text_contrast) — round-trip proven in tests/test_remediate_pdf_contrast.py.
      expect(isAuto(CAP, 'docx', '1.4.3')).toBe(true)
      expect(isAuto(CAP, 'xlsx', '1.4.3')).toBe(true)
      expect(isAuto(CAP, 'pptx', '1.4.3')).toBe(true)
      expect(isAuto(CAP, 'html', '1.4.3')).toBe(true)
      expect(isAuto(CAP, 'pdf', '1.4.3')).toBe(true)
    })
    it('language 3.1.1 is auto on every format that carries it', () => {
      for (const fmt of ['docx', 'pptx', 'xlsx', 'pdf', 'html']) {
        expect(isAuto(CAP, fmt, '3.1.1')).toBe(true)
      }
    })
  })

  describe('contrast review-recommended policy (layered on top of the capability)', () => {
    it('flags 1.4.3 and 1.4.6 as review-recommended', () => {
      expect(reviewRecommended('1.4.3')).toBe(true)
      expect(reviewRecommended('1.4.6')).toBe(true)
      expect(REVIEW_RECOMMENDED_SC.has('1.4.3')).toBe(true)
    })
    it('does not touch other criteria', () => {
      expect(reviewRecommended('2.4.2')).toBe(false)
      expect(reviewRecommended('1.1.1')).toBe(false)
    })
    it('is a policy, NOT a capability change: contrast stays auto where a remediator exists', () => {
      // The review-recommended flag shifts wording/recommendation only — the capability still
      // reports contrast as technically auto-fixable on the formats with a remediator.
      expect(isAuto(CAP, 'docx', '1.4.3')).toBe(true)
      expect(isAuto(CAP, 'xlsx', '1.4.3')).toBe(true)
      expect(isAuto(CAP, 'pptx', '1.4.3')).toBe(true)
      expect(isAuto(CAP, 'html', '1.4.3')).toBe(true)
    })
  })

  describe('alt text — assisted where a proposer backs it, human on external HTML images', () => {
    it('marks 1.1.1 assisted on every embedded-image format', () => {
      for (const fmt of ['docx', 'pptx', 'xlsx', 'pdf']) {
        expect(modeFor(CAP, fmt, '1.1.1')).toBe('assisted')
        expect(isAuto(CAP, fmt, '1.1.1')).toBe(false)
      }
    })
    it('marks html 1.1.1 human — an external <img> is never fetched, so no proposer backs it', () => {
      expect(modeFor(CAP, 'html', '1.1.1')).toBe('human')
    })
  })
})

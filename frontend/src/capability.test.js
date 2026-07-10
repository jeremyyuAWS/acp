import { describe, it, expect } from 'vitest'
import { CAPABILITY_FALLBACK, fmtOf, modeFor, isAuto, autoSCs } from './capability.js'

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
      expect(autoSCs(CAP, 'docx')).toEqual(new Set(['2.4.2', '1.3.1', '2.4.6', '1.4.3']))
    })
    it('includes docx contrast (1.4.3), which the old hand map omitted', () => {
      expect(isAuto(CAP, 'docx', '1.4.3')).toBe(true)
    })
    it('treats docx language (3.1.1) as human — engine-blocked, not auto', () => {
      expect(isAuto(CAP, 'docx', '3.1.1')).toBe(false)
      expect(modeFor(CAP, 'docx', '3.1.1')).toBe('human')
    })
  })

  describe('format-awareness: the same criterion differs by format', () => {
    it('contrast 1.4.3 is auto on docx/xlsx/html but human on pptx/pdf', () => {
      expect(isAuto(CAP, 'docx', '1.4.3')).toBe(true)
      expect(isAuto(CAP, 'xlsx', '1.4.3')).toBe(true)
      expect(isAuto(CAP, 'html', '1.4.3')).toBe(true)
      expect(isAuto(CAP, 'pptx', '1.4.3')).toBe(false)
      expect(isAuto(CAP, 'pdf', '1.4.3')).toBe(false)
    })
    it('language 3.1.1 is auto on pptx/xlsx/pdf/html but human on docx', () => {
      expect(isAuto(CAP, 'pptx', '3.1.1')).toBe(true)
      expect(isAuto(CAP, 'xlsx', '3.1.1')).toBe(true)
      expect(isAuto(CAP, 'pdf', '3.1.1')).toBe(true)
      expect(isAuto(CAP, 'html', '3.1.1')).toBe(true)
      expect(isAuto(CAP, 'docx', '3.1.1')).toBe(false)
    })
  })

  describe('alt text is assisted everywhere — never a silent auto-apply', () => {
    it('marks 1.1.1 assisted on every image-bearing format', () => {
      for (const fmt of ['html', 'docx', 'pptx', 'xlsx', 'pdf']) {
        expect(modeFor(CAP, fmt, '1.1.1')).toBe('assisted')
        expect(isAuto(CAP, fmt, '1.1.1')).toBe(false)
      }
    })
  })
})

import { describe, it, expect } from 'vitest'
import { SET_STATUS, isHeldDoc, certificationUniverse, releaseSetStatus } from './graduation.js'

// Small builders for the file shapes Publish hands the model.
const verified = (file, over = {}) => ({ file, compliant: true, score: 100, ...over })
const held = (file, over = {}) => ({ file, compliant: false, score: 40, issues: [{ wcag: 'SC_1_1_1' }], ...over })
const discover = (file, over = {}) => ({ file, compliant: false, score: null, ...over })

describe('W5 — conditional-to-full graduation model', () => {
  describe('isHeldDoc / certificationUniverse', () => {
    it('a compliant document is never held', () => {
      expect(isHeldDoc(verified('a.pdf'))).toBe(false)
    })
    it('an assessed document with open findings is held', () => {
      expect(isHeldDoc(held('b.pdf'))).toBe(true)
    })
    it('an assessed document with a score but no findings array is held (not compliant)', () => {
      expect(isHeldDoc({ file: 'c.pdf', compliant: false, score: 55 })).toBe(true)
    })
    it('a never-assessed / discover-only record is NOT part of the set', () => {
      expect(isHeldDoc(discover('d.pdf'))).toBe(false)
    })
    it('the universe is verified + held, excluding discover-only', () => {
      const files = [verified('a.pdf'), held('b.pdf'), discover('d.pdf')]
      expect(certificationUniverse(files).map((f) => f.file)).toEqual(['a.pdf', 'b.pdf'])
    })
  })

  describe('releaseSetStatus', () => {
    it('is NONE when nothing has been released yet', () => {
      const r = releaseSetStatus([verified('a.pdf'), held('b.pdf')], {})
      expect(r.status).toBe(SET_STATUS.NONE)
    })

    it('is CONDITIONAL when the verified docs are released but a document is still held', () => {
      const files = [verified('a.pdf'), held('b.pdf')]
      const r = releaseSetStatus(files, { 'a.pdf': true })
      expect(r.status).toBe(SET_STATUS.CONDITIONAL)
      expect(r.released).toBe(1)
      expect(r.heldOpen).toBe(1)
      expect(r.graduatable).toEqual([])
    })

    it('becomes GRADUATABLE once every held document is now verified (remediated), still unreleased', () => {
      // b.pdf was held at release time; it has since been remediated → compliant, not yet released.
      const files = [verified('a.pdf'), verified('b.pdf')]
      const r = releaseSetStatus(files, { 'a.pdf': true })
      expect(r.status).toBe(SET_STATUS.GRADUATABLE)
      expect(r.heldOpen).toBe(0)
      expect(r.verifiedUnreleased).toBe(1)
      expect(r.graduatable).toEqual(['b.pdf'])
    })

    it('stays CONDITIONAL while ANY document is still genuinely held', () => {
      // b.pdf remediated (verified, unreleased) but c.pdf still has open findings.
      const files = [verified('a.pdf'), verified('b.pdf'), held('c.pdf')]
      const r = releaseSetStatus(files, { 'a.pdf': true })
      expect(r.status).toBe(SET_STATUS.CONDITIONAL)
      expect(r.heldOpen).toBe(1)
      expect(r.verifiedUnreleased).toBe(1)
      // b.pdf can be graduated in; c.pdf cannot until it passes.
      expect(r.graduatable).toEqual(['b.pdf'])
    })

    it('is FULL once every document in the set is released', () => {
      const files = [verified('a.pdf'), verified('b.pdf')]
      const r = releaseSetStatus(files, { 'a.pdf': true, 'b.pdf': true })
      expect(r.status).toBe(SET_STATUS.FULL)
      expect(r.graduatable).toEqual([])
    })

    it('counts a persisted published_at and an externally-certified file as released', () => {
      const files = [verified('a.pdf', { published_at: '2026-08-01T00:00:00Z' }), verified('b.pdf')]
      const r = releaseSetStatus(files, {}, [{ file: 'b.pdf' }])
      expect(r.status).toBe(SET_STATUS.FULL)
    })

    it('the first "release all" of a set with held docs reads as CONDITIONAL, not full', () => {
      // Publish releases every compliant file at once; the held ones remain.
      const files = certificationUniverse([verified('a.pdf'), verified('b.pdf'), held('c.pdf'), discover('z.pdf')])
      const r = releaseSetStatus(files, { 'a.pdf': true, 'b.pdf': true })
      expect(r.status).toBe(SET_STATUS.CONDITIONAL)
      expect(r.total).toBe(3)           // z.pdf (discover-only) is excluded from the set
      expect(r.heldOpen).toBe(1)
    })
  })
})

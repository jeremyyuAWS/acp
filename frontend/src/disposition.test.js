import { describe, it, expect } from 'vitest'
import {
  DISPOSITION, DISPOSITION_KEYS, DISPOSITIONABLE_OUTCOMES, isDispositionable,
  dispositionByKey, normalizeDisposition, isResolved, dispositionLabel,
} from './disposition.js'

describe('W4 — disposition model for dead-end criteria', () => {
  describe('which outcomes are dispositionable', () => {
    it('covers the genuinely dead-end outcomes: UNCHECKED, GAP, AT', () => {
      expect(isDispositionable('UNCHECKED')).toBe(true)
      expect(isDispositionable('GAP')).toBe(true)
      expect(isDispositionable('AT')).toBe(true)
    })
    it('excludes HUMAN — it already has an onward path (the HITL review queue)', () => {
      expect(isDispositionable('HUMAN')).toBe(false)
    })
    it('excludes NA, PASS, FAIL, FIXED, REVIEW — none of them dead-end', () => {
      for (const o of ['NA', 'PASS', 'FAIL', 'FIXED', 'REVIEW', 'WEB']) {
        expect(isDispositionable(o)).toBe(false)
      }
    })
    it('DISPOSITIONABLE_OUTCOMES is exactly those three', () => {
      expect([...DISPOSITIONABLE_OUTCOMES].sort()).toEqual(['AT', 'GAP', 'UNCHECKED'])
    })
  })

  describe('the two dispositions', () => {
    it('exposes attested and out_of_scope keys', () => {
      expect(DISPOSITION_KEYS.sort()).toEqual(['attested', 'out_of_scope'])
    })
    it('attested resolves toward conformance; out_of_scope does not', () => {
      expect(DISPOSITION.ATTESTED.resolvesConformance).toBe(true)
      expect(DISPOSITION.OUT_OF_SCOPE.resolvesConformance).toBe(false)
    })
    it('looks a disposition up by key, and returns null for an unknown key', () => {
      expect(dispositionByKey('attested')).toBe(DISPOSITION.ATTESTED)
      expect(dispositionByKey('out_of_scope')).toBe(DISPOSITION.OUT_OF_SCOPE)
      expect(dispositionByKey('waved-through')).toBeNull()
      expect(dispositionByKey(undefined)).toBeNull()
    })
  })

  describe('normalizeDisposition — a reason is mandatory', () => {
    it('accepts a well-formed attestation', () => {
      const d = normalizeDisposition({ kind: 'attested', reason: 'Verified with NVDA', actor: 'a@b.co', at: '2026-08-18' })
      expect(d).toEqual({ kind: 'attested', reason: 'Verified with NVDA', actor: 'a@b.co', at: '2026-08-18' })
    })
    it('trims the reason', () => {
      expect(normalizeDisposition({ kind: 'out_of_scope', reason: '  contract excludes video  ' }).reason)
        .toBe('contract excludes video')
    })
    it('rejects a disposition with no reason — the whole point of the lane is an auditable reason', () => {
      expect(normalizeDisposition({ kind: 'attested', reason: '' })).toBeNull()
      expect(normalizeDisposition({ kind: 'attested', reason: '   ' })).toBeNull()
      expect(normalizeDisposition({ kind: 'attested' })).toBeNull()
    })
    it('rejects an unrecognised kind', () => {
      expect(normalizeDisposition({ kind: 'skip', reason: 'because' })).toBeNull()
    })
    it('rejects null / undefined', () => {
      expect(normalizeDisposition(null)).toBeNull()
      expect(normalizeDisposition(undefined)).toBeNull()
    })
    it('defaults actor and at to null when absent', () => {
      const d = normalizeDisposition({ kind: 'attested', reason: 'ok' })
      expect(d.actor).toBeNull()
      expect(d.at).toBeNull()
    })
  })

  describe('isResolved / dispositionLabel', () => {
    it('isResolved mirrors a valid normalized disposition', () => {
      expect(isResolved({ kind: 'attested', reason: 'done' })).toBe(true)
      expect(isResolved({ kind: 'attested', reason: '' })).toBe(false)
      expect(isResolved(null)).toBe(false)
    })
    it('renders a one-line label with the kind and the reason', () => {
      expect(dispositionLabel({ kind: 'attested', reason: 'Verified with NVDA' }))
        .toBe('Manually attested — Verified with NVDA')
      expect(dispositionLabel({ kind: 'out_of_scope', reason: 'contract excludes video' }))
        .toBe('Out of scope — contract excludes video')
    })
    it('renders an empty label for an invalid disposition', () => {
      expect(dispositionLabel({ kind: 'attested', reason: '' })).toBe('')
      expect(dispositionLabel(null)).toBe('')
    })
  })
})

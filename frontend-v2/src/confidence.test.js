import { describe, it, expect } from 'vitest'
import { CONFIDENCE, methodForSc, confidenceForFinding, confidenceForPii, confidenceForCoverage, confClass } from './confidence.js'

describe('evidence-based confidence model', () => {
  describe('methodForSc — derived from the maintained catalog tier', () => {
    it('maps Tier 1 deterministic criteria to deterministic', () => {
      expect(methodForSc('1.4.3')).toBe('deterministic')  // Contrast — Tier 1
      expect(methodForSc('2.4.2')).toBe('deterministic')  // Page Titled — Tier 1
      expect(methodForSc('3.1.1')).toBe('deterministic')  // Language of Page — Tier 1
    })
    it('maps Tier 2 agentic/heuristic criteria to heuristic', () => {
      expect(methodForSc('1.1.1')).toBe('heuristic')  // alt text
      expect(methodForSc('2.4.4')).toBe('heuristic')  // link purpose
      expect(methodForSc('1.3.1')).toBe('heuristic')  // info & relationships
      expect(methodForSc('4.1.2')).toBe('heuristic')  // name/role/value
    })
    it('maps Tier 3 HITL criteria to human', () => {
      expect(methodForSc('1.2.4')).toBe('human')  // Captions (Live) — HITL
      expect(methodForSc('3.3.1')).toBe('human')  // Error Identification — HITL
    })
    it('returns unknown for an unrecognised SC', () => {
      expect(methodForSc('9.9.9')).toBe('unknown')
      expect(methodForSc('')).toBe('unknown')
    })
  })

  describe('confidenceForFinding', () => {
    it('is HIGH for a deterministic open finding', () => {
      const c = confidenceForFinding({ sc: '1.4.3' })
      expect(c.level).toBe(CONFIDENCE.HIGH)
      expect(c.basis).toMatch(/deterministic rule check/)
    })
    it('is MEDIUM for a heuristic/AI open finding', () => {
      const c = confidenceForFinding({ sc: '1.1.1' })
      expect(c.level).toBe(CONFIDENCE.MEDIUM)
      expect(c.basis).toMatch(/heuristic/)
    })
    it('is LOW for a human-only open finding', () => {
      const c = confidenceForFinding({ sc: '3.3.1' })
      expect(c.level).toBe(CONFIDENCE.LOW)
      expect(c.basis).toMatch(/human review/)
    })
    it('a verified re-scan clear beats everything — even a Tier 3 criterion', () => {
      const c = confidenceForFinding({ sc: '3.3.1', verifiedCleared: true })
      expect(c.level).toBe(CONFIDENCE.HIGH)
      expect(c.basis).toMatch(/cleared on re-scan/)
    })
    it('an applied-but-unconfirmed fix is only MEDIUM (never blindly trusted High)', () => {
      const c = confidenceForFinding({ sc: '1.4.3', reportedFixedUnverified: true })
      expect(c.level).toBe(CONFIDENCE.MEDIUM)
      expect(c.basis).toMatch(/confirmation pending/)
    })
    it('verifiedCleared takes precedence over reportedFixedUnverified', () => {
      const c = confidenceForFinding({ sc: '1.1.1', verifiedCleared: true, reportedFixedUnverified: true })
      expect(c.level).toBe(CONFIDENCE.HIGH)
    })
    it('defaults to MEDIUM (never High) for an unknown SC — no over-claiming', () => {
      expect(confidenceForFinding({ sc: '9.9.9' }).level).toBe(CONFIDENCE.MEDIUM)
      expect(confidenceForFinding({}).level).toBe(CONFIDENCE.MEDIUM)
    })

    describe('AI proposal awaiting one-click approval', () => {
      it('a validated deterministic proposal is MEDIUM (never High — a human has not approved yet)', () => {
        const c = confidenceForFinding({ sc: '2.4.4', proposal: { validated: true, subjective: false } })
        expect(c.level).toBe(CONFIDENCE.MEDIUM)
        expect(c.basis).toMatch(/validated by re-scan/)
      })
      it('an unvalidated proposal is MEDIUM (approve to apply)', () => {
        const c = confidenceForFinding({ sc: '2.4.4', proposal: { validated: false, subjective: false } })
        expect(c.level).toBe(CONFIDENCE.MEDIUM)
        expect(c.basis).toMatch(/approve to apply/)
      })
      it('a subjective proposal (decorative / sensory) is LOW even if validated', () => {
        const c = confidenceForFinding({ sc: '1.1.1', proposal: { validated: true, subjective: true } })
        expect(c.level).toBe(CONFIDENCE.LOW)
        expect(c.basis).toMatch(/human judgement/)
      })
      it('a verified re-scan clear still outranks a proposal', () => {
        const c = confidenceForFinding({ sc: '2.4.4', verifiedCleared: true, proposal: { validated: true } })
        expect(c.level).toBe(CONFIDENCE.HIGH)
      })
    })
  })

  describe('confidenceForPii — mirrors the api/pii.py validation gate', () => {
    it('is HIGH for checksum-validated types (SSN, credit card)', () => {
      expect(confidenceForPii('ssn').level).toBe(CONFIDENCE.HIGH)
      expect(confidenceForPii('credit_card').level).toBe(CONFIDENCE.HIGH)
      expect(confidenceForPii('ssn').basis).toMatch(/checksum-validated/)
    })
    it('is MEDIUM for pattern-only types (email, phone, IP)', () => {
      expect(confidenceForPii('email').level).toBe(CONFIDENCE.MEDIUM)
      expect(confidenceForPii('phone').level).toBe(CONFIDENCE.MEDIUM)
      expect(confidenceForPii('ip').level).toBe(CONFIDENCE.MEDIUM)
      expect(confidenceForPii('email').basis).toMatch(/not checksum-validated/)
    })
  })

  describe('no fabricated percentages anywhere', () => {
    it('never emits a numeric confidence — only enum + basis string', () => {
      const samples = [
        confidenceForFinding({ sc: '1.4.3' }),
        confidenceForFinding({ sc: '1.1.1' }),
        confidenceForFinding({ sc: '3.3.1', verifiedCleared: true }),
        confidenceForPii('ssn'),
        confidenceForPii('email'),
      ]
      for (const c of samples) {
        expect(typeof c.level.label).toBe('string')
        expect(['High', 'Medium', 'Low']).toContain(c.level.label)
        expect(c.basis).not.toMatch(/\d+\s*%/)   // never a "42%"-style number
        expect(JSON.stringify(c)).not.toMatch(/%/)
      }
    })
  })

  describe('confidenceForCoverage', () => {
    it('makes NO assertion (null) for unchecked / web-only verdicts', () => {
      expect(confidenceForCoverage({ sc: '1.4.3', outcome: 'UNCHECKED' })).toBe(null)
      expect(confidenceForCoverage({ sc: '1.4.4', outcome: 'WEB' })).toBe(null)
    })
    it('is LOW for a HUMAN verdict even on a Tier 1 criterion (no automated signal)', () => {
      const c = confidenceForCoverage({ sc: '1.4.1', outcome: 'HUMAN' })  // 1.4.1 is Tier 1
      expect(c.level).toBe(CONFIDENCE.LOW)
      expect(c.basis).toMatch(/no automated signal/)
    })
    it('is HIGH for a verified-cleared FIXED row', () => {
      expect(confidenceForCoverage({ sc: '1.1.1', outcome: 'FIXED', verifiedCleared: true }).level).toBe(CONFIDENCE.HIGH)
    })
    it('is MEDIUM for a FIXED row not yet re-scan-confirmed', () => {
      const c = confidenceForCoverage({ sc: '1.4.3', outcome: 'FIXED', verifiedCleared: false })
      expect(c.level).toBe(CONFIDENCE.MEDIUM)
      expect(c.basis).toMatch(/confirmation pending/)
    })
    it('a PASS/FAIL row inherits its detection-method confidence', () => {
      expect(confidenceForCoverage({ sc: '1.4.3', outcome: 'PASS' }).level).toBe(CONFIDENCE.HIGH)   // deterministic
      expect(confidenceForCoverage({ sc: '1.1.1', outcome: 'FAIL' }).level).toBe(CONFIDENCE.MEDIUM)  // heuristic
    })
    it('(W4) a manually-attested dead-end criterion reads as a Low human attestation, not an automated pass', () => {
      const c = confidenceForCoverage({ sc: '1.2.1', outcome: 'UNCHECKED', disposition: 'attested' })
      expect(c.level).toBe(CONFIDENCE.LOW)
      expect(c.short).toBe('Attested')
      expect(c.basis).toMatch(/manually attested/)
      // accepts the record object too, not just the kind string
      expect(confidenceForCoverage({ sc: '1.2.1', outcome: 'AT', disposition: { kind: 'attested', reason: 'x' } }).short).toBe('Attested')
    })
    it('(W4) an out-of-scope criterion leaves the scope — the platform makes NO assertion (null)', () => {
      expect(confidenceForCoverage({ sc: '1.2.1', outcome: 'UNCHECKED', disposition: 'out_of_scope' })).toBe(null)
      expect(confidenceForCoverage({ sc: '1.2.1', outcome: 'GAP', disposition: { kind: 'out_of_scope', reason: 'x' } })).toBe(null)
    })
  })

  describe('confClass', () => {
    it('builds the themed chip class from the level key', () => {
      expect(confClass(CONFIDENCE.HIGH)).toBe('conf conf-high')
      expect(confClass(CONFIDENCE.LOW)).toBe('conf conf-low')
      expect(confClass(undefined)).toBe('conf conf-medium')
    })
  })
})

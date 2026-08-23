import { describe, it, expect } from 'vitest'
import { SEV_DOT, SEV_BG, SEV_FG, SEV_LABEL, SEV_TIP } from './severityColors.js'

const LEVELS = ['CRITICAL', 'SERIOUS', 'MODERATE', 'MINOR']

describe('severityColors', () => {
  it('exports SEV_DOT for all four severity levels', () => {
    for (const lvl of LEVELS) {
      expect(SEV_DOT[lvl], `SEV_DOT missing ${lvl}`).toBeTruthy()
      expect(typeof SEV_DOT[lvl]).toBe('string')
    }
  })

  it('exports SEV_BG for all four severity levels', () => {
    for (const lvl of LEVELS) {
      expect(SEV_BG[lvl], `SEV_BG missing ${lvl}`).toBeTruthy()
    }
  })

  it('exports SEV_FG for all four severity levels', () => {
    for (const lvl of LEVELS) {
      expect(SEV_FG[lvl], `SEV_FG missing ${lvl}`).toBeTruthy()
    }
  })

  it('exports SEV_LABEL for all four severity levels', () => {
    expect(SEV_LABEL.CRITICAL).toBe('Critical')
    expect(SEV_LABEL.SERIOUS).toBe('Serious')
    expect(SEV_LABEL.MODERATE).toBe('Moderate')
    expect(SEV_LABEL.MINOR).toBe('Minor')
  })

  it('exports SEV_TIP for all four severity levels', () => {
    for (const lvl of LEVELS) {
      expect(SEV_TIP[lvl], `SEV_TIP missing ${lvl}`).toBeTruthy()
      expect(typeof SEV_TIP[lvl]).toBe('string')
      expect(SEV_TIP[lvl].length).toBeGreaterThan(10)
    }
  })

  it('CRITICAL dot is darker/more urgent than MINOR', () => {
    // CRITICAL and SERIOUS should not have the same color as MINOR
    expect(SEV_DOT.CRITICAL).not.toBe(SEV_DOT.MINOR)
    expect(SEV_DOT.SERIOUS).not.toBe(SEV_DOT.MINOR)
  })

  it('all dot colors are valid CSS hex colors', () => {
    for (const lvl of LEVELS) {
      expect(SEV_DOT[lvl]).toMatch(/^#[0-9A-Fa-f]{6}$/)
    }
  })
})

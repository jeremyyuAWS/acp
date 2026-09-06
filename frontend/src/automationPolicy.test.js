import { describe, expect, it } from 'vitest'
import { automationForecast, automationLevel } from './automationPolicy.js'

const finding = (overrides = {}) => ({
  rule_id: 'WCAG_2_4_4',
  hasProposal: true,
  proposals: [{ proposed_value: 'Descriptive link text' }],
  ...overrides,
})

describe('automationForecast', () => {
  it('adds supported AI proposals only at Assisted and above', () => {
    expect(automationForecast([finding()], 3).candidates).toBe(0)
    expect(automationForecast([finding()], 4).candidates).toBe(1)
  })

  it('adds validated proposals at Balanced', () => {
    expect(automationForecast([finding({ validated: true })], 3)).toMatchObject({ candidates: 1, review: 0 })
  })

  it('never routes subjective, missing-proposal, or human-only findings automatically', () => {
    const rows = [
      finding({ proposals: [{ proposed_value: '', kind: 'decorative' }] }),
      finding({ hasProposal: false, proposals: [] }),
      finding({ rule_id: 'WCAG_1_3_3' }),
    ]
    expect(automationForecast(rows, 5)).toEqual({ total: 3, candidates: 0, protected: 3, review: 3 })
  })

  it('falls back to Balanced for an invalid level', () => {
    expect(automationLevel(99).name).toBe('Balanced')
  })
})

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

  it('adds validated non-deterministic proposals at Balanced', () => {
    expect(automationForecast([finding({ validated: true })], 3)).toMatchObject({ candidates: 1, review: 0 })
  })

  it('requires stored validation before Strict admits deterministic work', () => {
    const deterministic = finding({ rule_id: 'WCAG_1_4_3' })
    expect(automationForecast([deterministic], 1)).toMatchObject({ candidates: 0, review: 1 })
    expect(automationForecast([{ ...deterministic, validated: true }], 1))
      .toMatchObject({ candidates: 1, review: 0 })
  })

  it('never routes subjective, missing-proposal, or human-only findings automatically', () => {
    const rows = [
      finding({ proposals: [{ proposed_value: '', kind: 'decorative' }] }),
      finding({ hasProposal: false, proposals: [] }),
      finding({ rule_id: 'WCAG_1_3_3' }),
    ]
    expect(automationForecast(rows, 5)).toEqual({ total: 3, candidates: 0, protected: 3, review: 0 })
  })

  it('partitions every finding into exactly one visible forecast tile', () => {
    const result = automationForecast([
      finding(),
      finding({ rule_id: 'WCAG_1_4_3' }),
      finding({ hasProposal: false, proposals: [] }),
    ], 3)
    expect(result.candidates + result.review + result.protected).toBe(result.total)
  })

  it('falls back to Balanced for an invalid level', () => {
    expect(automationLevel(99).name).toBe('Balanced')
  })
})

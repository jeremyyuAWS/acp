import { describe, it, expect } from 'vitest'
import { remediationTrack } from './remediationTrack.js'

describe('remediationTrack — the two-track apply model', () => {
  it('deterministic SC → auto-applied (never held behind a human click)', () => {
    const t = remediationTrack({ sc: '1.4.3' })          // contrast, Tier 1
    expect(t.track).toBe('auto')
    expect(t.action).toBe('Auto-applied')
    expect(t.badge.tone).toBe('auto')
  })

  it('language / title deterministic → auto', () => {
    expect(remediationTrack({ sc: '3.1.1' }).track).toBe('auto')
  })

  it('alt text → assisted (AI proposes, human one-click approves)', () => {
    const t = remediationTrack({ sc: '1.1.1' })          // Tier 2 + semantic value
    expect(t.track).toBe('assisted')
    expect(t.action).toBe('Approve & Apply')
  })

  it('link purpose → assisted', () => {
    expect(remediationTrack({ sc: '2.4.4' }).track).toBe('assisted')
  })

  it('keyboard is human-required even though the catalog labels it Tier 1 (detect ≠ fix)', () => {
    expect(remediationTrack({ sc: '2.1.1' }).track).toBe('human')
    expect(remediationTrack({ sc: '2.1.2' }).track).toBe('human')
    expect(remediationTrack({ sc: '1.4.5' }).badge.tone).toBe('human')
  })

  it('a Low-confidence deterministic result is demoted to assisted (never over-claims auto)', () => {
    expect(remediationTrack({ sc: '1.4.3', confidence: { level: { key: 'low' } } }).track).toBe('assisted')
  })

  it('accepts SC_-prefixed / underscored ids', () => {
    expect(remediationTrack({ sc: 'SC_1_4_3' }).track).toBe('auto')
  })
})

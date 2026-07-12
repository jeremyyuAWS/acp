import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { reviewRisk, riskComparator, fmtEst } from './reviewRisk.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

// hitlMeta.sevOf reads a rule→severity map; use rules with known severities via metaFor's default.
const confirmItem = { rule_id: 'auto/verify', proposals: [] }                 // deterministic confirm
const authorItem = { rule_id: '1.1.1', proposals: [] }                        // no draft → manual
const groundedProposal = { rule_id: '1.1.1', proposals: [{ proposed_value: 'Bar chart', grounded: true }] }
const ungroundedProposal = { rule_id: '1.1.1', proposals: [{ proposed_value: 'A photo', grounded: false }] }

describe('reviewRisk — one tier + estimated effort from real signals (roadmap #6)', () => {
  it('a deterministic confirmation is Low / quick', () => {
    const r = reviewRisk(confirmItem)
    expect(r.key).toBe('low')
    expect(r.estSeconds).toBe(5)
  })

  it('manual authoring is the most effortful tier', () => {
    expect(reviewRisk(authorItem).key).toBe('critical')
  })

  it('a grounded proposal is a faster review than an ungrounded one', () => {
    expect(reviewRisk(groundedProposal).rank).toBeLessThan(reviewRisk(ungroundedProposal).rank)
  })

  it('exposes the honest factors behind the tier', () => {
    const r = reviewRisk(ungroundedProposal)
    expect(r.factors).toMatchObject({ reviewType: 'proposal', grounded: false })
  })

  it('estimate is formatted as an estimate, never a bare number', () => {
    expect(fmtEst(5)).toBe('~5s')
    expect(fmtEst(180)).toBe('~3 min')
  })

  it('comparator: critical-first vs quickest-first are opposite orders', () => {
    const items = [confirmItem, authorItem, ungroundedProposal]
    const crit = [...items].sort(riskComparator('critical')).map((i) => reviewRisk(i).key)
    const quick = [...items].sort(riskComparator('quick')).map((i) => reviewRisk(i).estSeconds)
    expect(crit[0]).toBe('critical')                       // hardest first
    expect(quick[0]).toBe(5)                               // easiest first
  })
})

describe('the inbox surfaces + sorts by risk', () => {
  it('ReviewCenter shows a RiskChip and sorts by the chosen mode', () => {
    const s = read('ReviewCenter.jsx')
    expect(s).toMatch(/import RiskChip from '.\/RiskChip.jsx'/)
    expect(s).toMatch(/riskComparator\(sortMode\)/)
    expect(s).toMatch(/setSortMode\('quick'\)/)
    expect(s).toMatch(/<RiskChip item=\{it\} compact \/>/)
  })
  it('the EvidenceCard header carries the risk tier + estimate', () => {
    expect(read('EvidenceCard.jsx')).toMatch(/<RiskChip item=\{item\} \/>/)
  })
})

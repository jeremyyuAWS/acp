import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { coreStats, scOfWcag } from './coreStats.js'
import { CAPABILITY_FALLBACK } from './capability.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('scOfWcag normalizes both finding spellings', () => {
  it('collapses the engine form and the axe form to the bare dotted SC', () => {
    expect(scOfWcag('SC_1_1_1')).toBe('1.1.1')
    expect(scOfWcag('1.1.1 Non-text Content')).toBe('1.1.1')
    expect(scOfWcag('1.4.3')).toBe('1.4.3')
    expect(scOfWcag('')).toBeUndefined()
    expect(scOfWcag(null)).toBeUndefined()
  })
})

describe('coreStats — document-core, capability-grounded split', () => {
  // docx 1.3.1 = auto, 1.1.1 = assisted; html 1.1.1 = human, 1.4.3 = auto (CAPABILITY_FALLBACK).
  const files = [
    { type: 'docx', issues: [
      { wcag: 'SC_1_3_1' },          // core · docx auto  → coreAutoFix
      { wcag: '1.1.1 Non-text' },    // core · docx assisted → needs person
      { wcag: 'SC_4_1_3' },          // NOT in DOCUMENTS_20 → excluded entirely
    ] },
    { type: 'html', issues: [
      { wcag: '1.1.1' },             // core · html human → needs person
      { wcag: '1.4.3' },             // core · html auto  → coreAutoFix
    ] },
  ]

  it('counts only DOCUMENTS_20 findings, split by capability lane', () => {
    const c = coreStats(files, CAPABILITY_FALLBACK)
    expect(c.coreFindings).toBe(4)          // 4.1.3 excluded
    expect(c.coreCriteria).toBe(3)          // {1.3.1, 1.1.1, 1.4.3} — 1.1.1 across two files counts once
    expect(c.coreAutoFix).toBe(2)           // docx 1.3.1 + html 1.4.3
    expect(c.coreHuman).toBe(2)
    expect(c.autoPct).toBe(50)
  })

  it('does not double-count the two wcag spellings when tallying criteria', () => {
    const dup = [{ type: 'docx', issues: [{ wcag: 'SC_1_3_1' }, { wcag: '1.3.1 Info and Relationships' }] }]
    const c = coreStats(dup, CAPABILITY_FALLBACK)
    expect(c.coreFindings).toBe(2)          // two findings
    expect(c.coreCriteria).toBe(1)          // one distinct criterion
  })

  it('respects the conformance level — an AAA finding is excluded at AA, included at AAA', () => {
    const withAAA = [{ type: 'docx', issues: [{ wcag: 'SC_1_4_3', level: 'AAA' }] }]
    expect(coreStats(withAAA, CAPABILITY_FALLBACK, 'AA').coreFindings).toBe(0)
    expect(coreStats(withAAA, CAPABILITY_FALLBACK, 'AAA').coreFindings).toBe(1)
  })

  it('is safe on empty / missing input', () => {
    expect(coreStats([], CAPABILITY_FALLBACK)).toMatchObject({ coreFindings: 0, coreCriteria: 0, coreAutoFix: 0, coreHuman: 0, autoPct: 0 })
    expect(coreStats(undefined, CAPABILITY_FALLBACK).coreFindings).toBe(0)
  })

  it('an unknown (fmt, sc) is never silently auto — it needs a person', () => {
    // 1.4.3 is a core criterion, but a null-format file has no capability entry → human, not auto.
    const noFmt = [{ issues: [{ wcag: 'SC_1_4_3' }] }]
    const c = coreStats(noFmt, CAPABILITY_FALLBACK)
    expect(c.coreFindings).toBe(1)
    expect(c.coreAutoFix).toBe(0)
  })
})

// The whole point of coreStats is that the Assess tile and the RiskScore panel CANNOT disagree
// about the document-core numbers, because they call the same function. Guard that wiring in source
// so a future edit can't quietly reintroduce a second, divergent computation.
describe('both consumers read the shared lens (no drift)', () => {
  it('AssessRunner derives its core* fields from coreStats, not an inline tally', () => {
    const src = read('AssessRunner.jsx')
    expect(src).toMatch(/import \{ coreStats \} from '\.\/coreStats\.js'/)
    expect(src).toMatch(/const core = coreStats\(scored, cap, lvl\)/)
    expect(src).not.toMatch(/coreFindings\+\+/)         // the old inline accumulation is gone
  })

  it('RiskScore reads coreStats and no longer touches the SIM-only rec', () => {
    const src = read('RiskScore.jsx')
    expect(src).toMatch(/import \{ coreStats.*\} from '\.\/coreStats\.js'/)
    expect(src).toMatch(/coreStats\(files, cap\)/)
    expect(src).not.toMatch(/recommendationSummary|rec\.autoPct|rec\.remediableDocs|rec\.remediateMin/)
  })
})

// Phase 2 — AssessRunner's result tiles are four decision-first KPI cards, every value read from
// `result` (→ coreStats), and the duplicate "pass rate %" tile is gone (it was a third rendering
// of the same estate failure the master ring + risk score already show). Guarded at source because
// the tiles have no DOM test and a regression to a bare pass-rate% is invisible in a diff.
describe('the Assess KPI cards are grounded and de-duplicated', () => {
  const src = read('AssessRunner.jsx')

  it('shows the four decision KPIs — documents needing action, findings, addressable, effort', () => {
    expect(src).toMatch(/documents need action/)
    expect(src).toMatch(/ACP fixes automatically/)
    expect(src).toMatch(/human effort/)
    expect(src).toMatch(/findings <span className="muted">· across/)
  })

  it('drops the duplicate pass-rate % tile (kept once as the score ring below)', () => {
    expect(src).not.toMatch(/pass rate at \{result\.level\}/)
    expect(src).not.toMatch(/\{result\.pct\}%<\/b>/)
  })

  it('estimates human effort through the labelled heuristic, never a raw number', () => {
    // effort.js honesty: rendered via fmtEffort ("est." prefix) with EFFORT_BASIS as the tooltip.
    expect(src).toMatch(/fmtEffort\(effortMin\)/)
    expect(src).toMatch(/title=\{EFFORT_BASIS\}/)
  })
})

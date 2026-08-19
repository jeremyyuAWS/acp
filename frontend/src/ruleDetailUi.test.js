import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Two claims, both about text a CUSTOMER reads:
//   1. the criterion table defaults to the 17 tracked criteria, not the 14 or the 20;
//   2. each row can say what ACP actually checks, from the generated rule docs.
//
// Source-level, same reasoning as the other v2 structure tests: these assert which constant the
// default is bound to and that nothing retypes a criteria list. A mount-based test would need a
// whole scan fixture, and one that rendered an empty table would pass "the 14 is not shown" by
// showing nothing at all.

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

describe('v2: the criterion table shows the tracked 17', () => {
  it('defaults to TRACKED_17 and widens to the 20', () => {
    const t = read('Transparency.jsx')
    expect(t).toMatch(/const criteria = showAllCore \? criteriaFor\(true\) : TRACKED_17/)
    expect(t).toContain("from './ruleDetails.js'")
  })

  it('never retypes the 17 — it comes from the generated module', () => {
    const t = read('Transparency.jsx')
    // A literal list of criteria in this file would be the sixth copy of a number this product
    // already quotes five ways. The generator + its CI guard is the only thing preventing that.
    expect(t).not.toMatch(/\[\s*'1\.1\.1'\s*,\s*'1\.3\.1'/)
    expect(existsSync(join(HERE, 'ruleDetails.js'))).toBe(true)
  })

  it('says why the extra three are not tracked, rather than just omitting them', () => {
    // "17 of 20" with no account of the other three reads as an oversight. The toggle explains
    // that resize / reflow / text spacing are viewer behaviours.
    expect(read('Transparency.jsx')).toMatch(/viewer behaviours/)
  })
})

describe('v2: per-rule assess / remediate detail', () => {
  it('renders a RuleDetail on each criterion row', () => {
    const t = read('Transparency.jsx')
    expect(t).toMatch(/function RuleDetail\(/)
    expect(t).toMatch(/<RuleDetail sc=\{r\.id\} \/>/)
  })

  it('shows both halves — what is assessed and what remediation does', () => {
    const t = read('Transparency.jsx')
    expect(t).toMatch(/<b>Assess:<\/b>/)
    expect(t).toMatch(/Remediate \(\{d\.fixMode\}\)/)
  })

  it('admits the gap instead of inventing remediation prose', () => {
    // Six of the 36 rule docs have no "Fix mode rationale". Those must say so, not be silently
    // dropped (which reads as "no remediation exists") and not be filled with a plausible
    // sentence (which the reader cannot distinguish from a real one).
    const t = read('Transparency.jsx')
    expect(t).toMatch(/not documented for this rule yet/)
    const js = read('ruleDetails.js')
    expect(js).toContain('remediation: null,')
  })

  it('carries the real detector prose, not a paraphrase', () => {
    // Spot-check the case that prompted this: 1.3.1 on DOCX is heading structure, and the
    // generated text must be the doc's own words about H1/H2 levels.
    const js = read('ruleDetails.js')
    expect(js).toMatch(/"DOCX-HEAD-001":/)
    expect(js).toMatch(/Heading 1\.\.9/)
    expect(js).toMatch(/"1\.3\.1": \[[^\]]*"DOCX-HEAD-001"/)
  })
})

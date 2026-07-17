import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { DOCUMENTS_20 } from './documents20.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')
const src = read('FileDrawer.jsx')

describe('Assess drawer coverage table — the document-core 20, assessed + remediation + gap/na', () => {
  it('shows strictly the 20-check document core — no show-all toggle', () => {
    expect(src).toMatch(/const inScope = WCAG\.filter\(\(c\) => c\.docApplies !== false && DOCUMENTS_20\.has\(c\.sc\)\)/)
    // the escape hatch is gone
    expect(src).not.toMatch(/coreOnly/)
    expect(src).not.toMatch(/setCoreOnly/)
    expect(src).not.toMatch(/Show all \$\{scoped/)
  })

  it('the 20-core source has exactly the 20 document-core criteria', () => {
    expect(DOCUMENTS_20.size).toBe(20)
    // one representative from each of the four slide groups
    for (const sc of ['1.1.1', '3.1.1', '1.4.3', '2.4.2']) expect(DOCUMENTS_20.has(sc)).toBe(true)
  })

  it('the Findings list is scoped to the 20 too, not just the coverage table', () => {
    // The engine also emits findings outside the 20 (3.3.2, 2.4.10, 1.4.8, 2.4.9, …); the whole
    // drawer must stay on the document core, so `issues` is filtered at its single source.
    expect(src).toMatch(/const issues = \(file\.issues \|\| \[\]\)\.filter\(\(i\) => DOCUMENTS_20\.has\(scOfWcag\(i\.wcag\)\)\)/)
  })

  it('header count chips double as filters — hide any outcome group (n/a, human, …)', () => {
    expect(src).toMatch(/const \[hidden, setHidden\] = useState\(\(\) => new Set\(\['NA'\]\)\)/)   // N/A hidden by default
    expect(src).toMatch(/const toggleOutcome = \(o\) => setHidden\(/)
    expect(src).toMatch(/const shown = rows\.filter\(\(r\) => !hidden\.has\(r\.outcome\)\)/)
    expect(src).toMatch(/onClick=\{\(e\) => \{ e\.preventDefault\(\); e\.stopPropagation\(\); toggleOutcome\(o\) \}\}/)
    expect(src).toMatch(/\{shown\.map\(\(r\) =>/)   // the table renders the filtered set
  })

  it('classifies each criterion by the capability truth (both axes), not just scan data', () => {
    expect(src).toMatch(/import \{ statusIn, remediationIn \} from '\.\/assessCoverage\.js'/)
    expect(src).toMatch(/const capStatus = fmt \? statusIn\(c\.sc, fmt\) : 'na'/)
    expect(src).toMatch(/const remLane = fmt \? remediationIn\(c\.sc, fmt\) : 'na'/)
    // honest labels: n/a and gap replace the misleading "not auto-checked" when nothing was found
    expect(src).toMatch(/capStatus === 'na' \? 'NA'/)
    expect(src).toMatch(/capStatus === 'gap' \? 'GAP'/)
    expect(src).toMatch(/capStatus === 'at' \? 'AT'/)
  })

  it('a real blocking finding wins; an advisory review finding surfaces as 🟡 REVIEW (ADR 0023)', () => {
    expect(src).toMatch(/count > 0 \? \(wasFixed \? 'FIXED' : 'FAIL'\)/)
    expect(src).toMatch(/reviewIssues\.length > 0 \? 'REVIEW'/)
    // a review-only lane with no signal is genuine N/A, never a fabricated pass
    expect(src).toMatch(/capStatus === 'review' && remLane === 'na'\) \? 'NA'/)
  })

  it('a 🟡 review-lane criterion with no finding is REVIEW ("verify"), never a certified pass (#174)', () => {
    // e.g. 1.1.1 with no missing alt — ACP can't certify alt adequacy, so it is NOT a green PASS.
    expect(src).toMatch(/: capStatus === 'review' \? 'REVIEW'/)
    expect(src).toMatch(/verify — none found/)
  })

  it('rows carry the remediation lane in the Fix column; none-lane rows show —', () => {
    expect(src).toMatch(/const fix = remLane !== 'na' \? fixOf\(c\) : '—'/)
  })

  it('surfaces the assess outcome AND the remediation lane, with gap/na/at explained', () => {
    expect(src).toMatch(/NA: 'n\/a for this type'/)
    expect(src).toMatch(/GAP: 'gap · not built'/)
    // the Fix column legend names the three remediation lanes
    expect(src).toMatch(/deterministic/)
    expect(src).toMatch(/1-click/)
  })
})

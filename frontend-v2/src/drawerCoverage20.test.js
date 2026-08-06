import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { SCOPE_SCS, CORE_SCS, OUT_OF_SCOPE_SCS } from './activeScope.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')
const src = read('FileDrawer.jsx')

describe('Assess drawer coverage table — the agreed scope, assessed + remediation + gap/na', () => {
  it('shows strictly the criteria in the agreed scope — no show-all toggle', () => {
    expect(src).toMatch(/const inScope = WCAG\.filter\(\(c\) => c\.docApplies !== false && SCOPE_SCS\.has\(c\.sc\)\)/)
    // the escape hatch is gone
    expect(src).not.toMatch(/coreOnly/)
    expect(src).not.toMatch(/setCoreOnly/)
    expect(src).not.toMatch(/Show all \$\{scoped/)
    expect(src).not.toMatch(/Deva/)                    // customer name never reaches the UI
  })

  it('narrows by criterion, NOT by (criterion, format)', () => {
    // The preset is per-format and `inScopeFmt` mirrors the backend gate, but applying it to the
    // ROW SET would blank this table for .html — the preset covers no html pair at all — and
    // would delete rows the table already explains better, since each carries its own format
    // verdict from statusIn(sc, fmt) and renders ⚪ n/a with a stated reason.
    // A CALL, not a mention — the comment above the row filter names `inScopeFmt` to explain why
    // it is deliberately not used, and a test that forbids the word forbids the explanation.
    expect(src).not.toMatch(/inScopeFmt\s*\(/)
    expect(src).toMatch(/const capStatus = fmt \? statusIn\(c\.sc, fmt\) : 'na'/)
  })

  it('the scope source is the 14 the backend defines, carved out of the document core', () => {
    expect(SCOPE_SCS.size).toBe(14)
    expect(CORE_SCS.size).toBe(20)
    expect(OUT_OF_SCOPE_SCS.size).toBe(6)
    // one representative from each of the four slide groups is still in scope
    for (const sc of ['1.1.1', '3.1.1', '1.4.3', '2.4.2']) expect(SCOPE_SCS.has(sc)).toBe(true)
  })

  it('the Findings list is scoped the same way, not just the coverage table', () => {
    // The engine also emits findings outside the scope (3.3.2, 2.4.10, 1.4.8, 2.4.9, and the six
    // document-core criteria this engagement did not ask about); the whole drawer must stay on one
    // list, so `issues` is filtered at its single source.
    expect(src).toMatch(/const issues = \(file\.issues \|\| \[\]\)\.filter\(\(i\) => SCOPE_SCS\.has\(scOfWcag\(i\.wcag\)\)\)/)
  })

  it('the CERTIFICATION EXPORT uses the same list as the table it mirrors', () => {
    // This was the widest list in the product and it fed the customer's evidence PDF: every
    // document-applicable criterion at/below target (42 at AA) while the manifest showed 20.
    // reportModel.js renders `rows.length` as "N of 42 in-scope criteria", so the certificate
    // asserted conformance over a denominator the screen never showed.
    expect(src).toMatch(/const inScope = WCAG\.filter\(\(c\) => c\.docApplies !== false && \(LEVEL_RANK\[c\.level\] \|\| 3\) <= targetRank\s*\n?\s*&& SCOPE_SCS\.has\(c\.sc\)\)/)
  })

  it('names the criteria it dropped, and any findings inside them, unconditionally', () => {
    expect(src).toMatch(/outOfScopeNote\(outOfScopeCount\)/)
    // Counted from the UNFILTERED issue list — `issues` has already dropped them.
    expect(src).toMatch(/const outOfScopeCount = \(file\.issues \|\| \[\]\)\s*\n?\s*\.filter\(\(i\) => OUT_OF_SCOPE_SCS\.has\(scOfIssue\(i\.wcag\)\)\)\.length/)
    // Not behind a `> 0` guard: a criterion missing from a certification record with no account
    // of itself is the trust problem whether or not it was failing.
    expect(src).not.toMatch(/outOfScopeCount > 0 && [\s\S]{0,80}outOfScopeNote/)
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

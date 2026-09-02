import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import Overview from './Overview.jsx'
import { mountExpanded } from './testAccordion.js'

// K8 · the compliance funnel re-skinned as a trapezoid — same `stages` data (Discover / Assess /
// Remediate / Verify / Publish) the old decreasing-bars form used, a different shape. Pins: the
// stage labels + counts still render, each stage's conversion-from-the-PREVIOUS-stage percentage
// is correct (not from the funnel's first stage), and a zero-document previous stage prints
// "no prior stage to convert from" rather than a division-by-zero 0%.

// n (Discover, Assess) comes from run.files; Verify from run.certifiable; Publish from how many
// FILES carry published_at. Chosen so Verify -> Publish (2 -> 1 = 50%) is a genuine, hand-checkable
// conversion distinct from Discover -> Assess, which is trivially 100% (both read the same `n`) and
// so can't tell "previous stage" logic apart from "first stage" logic on its own.
const RUN = {
  id: 's1', status: 'complete', avg_score: 71, certifiable: 2, files: 4,
  completed_at: '2026-08-20T16:04:00Z',
  scope: { kind: 'drive', inventory: { discovered: 4, assessment_eligible: 4, by_status: { assessable: 4 } } },
}

const FILES = [
  { file: 'a.docx', name: 'a.docx', status: 'done', score: 60,
    issues: [{ sc: '1.1.1', severity: 'CRITICAL' }] },
  { file: 'b.pdf', name: 'b.pdf', status: 'done', score: 90, issues: [] },
  { file: 'c.pdf', name: 'c.pdf', status: 'done', score: 90, issues: [] },
  { file: 'd.pdf', name: 'd.pdf', status: 'done', score: 90, issues: [], published_at: '2026-08-20T01:00:00Z' },
]

// The funnel is a disclosure that starts CLOSED (2026-09-02 UI simplification PRD) — it is a
// drill-down, not a headline. Every assertion here is therefore on the opened section, reached
// by clicking its header button, which is also what a reader has to do.
const render = (props = {}) =>
  mountExpanded(createElement(Overview, { run: RUN, files: FILES, trend: [], trendDates: [], onGo: () => {}, ...props })).innerHTML

describe('the compliance funnel, re-skinned as a trapezoid', () => {
  it('still shows every stage label and its count', () => {
    const html = render()
    for (const label of ['Discover', 'Assess', 'Remediate', 'Verify', 'Publish']) {
      // Not `>${label}<`: the JSX is `{s.label} {s.proj && <em>...}</em>}`, so a non-projected
      // stage renders "Discover " (a real trailing space before the closing tag) — the label is
      // followed by whatever comes next, not always immediately by `<`.
      expect(html).toMatch(new RegExp(`>${label}\\b`))
    }
  })

  it('prints the conversion rate from the PREVIOUS stage, not from the funnel start', () => {
    // Stages here are Discover=4, Assess=4, Remediate=0, Verify=2, Publish=1. Verify -> Publish is
    // 1/2 = 50%, which "always divide by the first stage" (4) would instead print as 25%.
    const html = render()
    expect(html).toMatch(/↓\s*50%/)
    expect(html).not.toMatch(/↓\s*25%/)
  })

  it('prints a real 0%, not "absent", when the CURRENT stage is genuinely zero', () => {
    // Assess=4 -> Remediate=0 is a real measurement (nothing needed remediation), not a missing
    // one — must render as "0%", the opposite failure mode from the null-previous-stage case below.
    const html = render()
    expect(html).toMatch(/↓\s*0%/)
  })

  it('has one fewer drop indicator than there are stages (nothing before the first)', () => {
    const html = render()
    const drops = html.match(/trapdrop/g) || []
    expect(drops.length).toBe(4)   // 5 stages, 4 gaps between them
  })

  it('says so, not "0%", when the PREVIOUS stage has nothing to convert from', () => {
    // Remediate=0 -> Verify=2 has no denominator: 2/0 is not "infinity%" and is not "0%" either.
    const html = render()
    expect(html).toContain('no prior stage to convert from')
  })

  it('keeps the click-through wired to the same stage-open handler', () => {
    // Renders as a real <button> per stage — renderToStaticMarkup can't simulate the click, but it
    // can confirm the trapezoid markup didn't drop the interactive element the old bars had.
    const html = render()
    expect((html.match(/class="trapstage"/g) || []).length).toBe(5)
  })
})

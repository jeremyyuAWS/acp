import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import Overview from './Overview.jsx'

// The Overview grows organically across the funnel (owner direction, 2026-08-20). It renders once an
// estate is DISCOVERED — reversing the old OV-01/OV-04 "blank until assessed" gate — and reveals each
// section as its stage completes: the discovery numbers first, the seven assessment metrics (board 4)
// once documents have actually been assessed. A discovered-not-assessed estate shows a prompt to run
// Assess, never a wall of empty findings charts, which is the concern the old gate was avoiding.

const INVENTORY = { discovered: 12408, assessment_eligible: 9000, by_status: { assessable: 9000 } }
const RUN = {
  id: 's1', status: 'complete', files: 12408, avg_score: 71, certifiable: 40,
  completed_at: '2026-08-20T16:04:00Z', scope: { kind: 'drive', inventory: INVENTORY },
}
const render = (files, props = {}) =>
  renderToStaticMarkup(createElement(Overview, {
    run: RUN, files, trend: [], trendDates: [], onGo: () => {}, ...props,
  }))

// analysed === 0: an inventoried estate nobody has assessed yet.
const DISCOVERED = [
  { file: 'a.docx', name: 'a.docx', status: 'discovered', score: null, issues: [] },
  { file: 'b.pdf', name: 'b.pdf', status: 'discovered', score: null, issues: [] },
]
// analysed > 0: two documents scored, one with findings.
const ASSESSED = [
  { file: 'a.docx', name: 'a.docx', status: 'done', score: 60,
    issues: [{ wcag: 'SC_1_1_1', severity: 'CRITICAL' }, { wcag: 'SC_1_3_1', severity: 'SERIOUS' }] },
  { file: 'b.pdf', name: 'b.pdf', status: 'done', score: 90, issues: [] },
]

describe('the Overview grows organically across the funnel', () => {
  it('shows the discovery numbers and a run-assessment prompt before anything is assessed', () => {
    const html = render(DISCOVERED)
    // Discovery has populated.
    expect(html).toContain('files discovered')
    // Assessment is a prompt, not a grid of zeros.
    expect(html).toContain('not yet run')
    expect(html).toContain('Run assessment')
    // The seven-metric section and the findings charts have NOT appeared yet.
    expect(html, 'the assessment metrics leaked before a run').not.toContain('aria-label="Assessment summary"')
    expect(html, 'a findings chart rendered over an unassessed estate').not.toContain('Compliance status')
    expect(html).not.toContain('Findings by severity')
  })

  it('reveals the seven assessment metrics once documents are assessed', () => {
    const html = render(ASSESSED)
    expect(html).toContain('aria-label="Assessment summary"')
    for (const label of ['documents assessed', 'needing attention', 'total findings',
                         'auto-fix available', 'human review required', 'unable to assess']) {
      expect(html, `missing assessment metric: ${label}`).toContain(label)
    }
    // The 7th metric — the severity partition, printed as an equation that sums to Total findings.
    expect(html).toMatch(/By severity:/)
    expect(html).toMatch(/=\s*2\b/)   // 1 critical + 1 serious + 0 + 0 = 2
    // The detailed findings charts are back now that there is something to chart.
    expect(html).toContain('Compliance status')
    // …and the prompt is gone.
    expect(html).not.toContain('Run assessment')
  })

  it('never shows two different findings totals — the section reads assessMetrics', () => {
    // The same module the Assess tab uses; 2 findings across the estate.
    const html = render(ASSESSED)
    expect(html).toMatch(/<span>total findings<\/span><b>2<\/b>/)
  })
})

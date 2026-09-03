import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import Overview from './Overview.jsx'

// The Overview's four headline tiles (approved board 7) — REMOVED on 2026-09-02 by the PRD "ACP
// Discover and Overview Simplification". EstateProgressPanel's stage funnel carries those values;
// a separate row repeating the same four numbers is intentionally absent.
//
// This file is kept, and rewritten to pin the removal, because the tiles were removed once before
// for being the WRONG four — `documents` counted the scan's file ROWS while the panel beneath it
// partitioned the DISCOVERED estate, and `certifiable` / `audit-ready` are the score #545 removed
// from Assess in other clothes. This screen exports as the compliance report, so a removed verdict
// creeping back in as a tile matters more than it looks. The invariants below are therefore stated
// against the funnel that renders the headline today.

const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'Overview.jsx'), 'utf8')

const INVENTORY = { discovered: 12408, assessment_eligible: 9000, by_status: { assessable: 9000 } }

const RUN = {
  id: 's1', status: 'complete', avg_score: 71, certifiable: 40,
  completed_at: '2026-08-20T16:04:00Z',
  scope: { kind: 'drive', inventory: INVENTORY },
}

const FILES = [
  { file: 'a.docx', name: 'a.docx', status: 'done', score: 60,
    issues: [{ sc: '1.1.1', severity: 'CRITICAL' }, { sc: '1.3.1', severity: 'SERIOUS' }] },
  { file: 'b.pdf', name: 'b.pdf', status: 'done', score: 90, issues: [] },
]

const render = (props = {}) =>
  renderToStaticMarkup(createElement(Overview, {
    run: RUN, files: FILES, trend: [], trendDates: [], onGo: () => {}, ...props,
  }))

describe('the four headline tiles are gone, and stay gone', () => {
  it('renders none of the four tile labels', () => {
    const html = render()
    for (const label of ['files discovered', 'assessed against WCAG', 'documents need action', 'findings']) {
      expect(html).not.toContain(`<span>${label}</span>`)
    }
  })

  it('drops certifiable and audit-ready, which are the removed score in other clothes', () => {
    const html = render()
    expect(html).not.toContain('<span>certifiable</span>')
    expect(html).not.toContain('<span>audit-ready</span>')
    // and the old row-count tile
    expect(html).not.toContain('<span>documents</span>')
  })
})

describe('the stage funnel is the single visible source for the four estate values', () => {
  it('does not render the duplicate metric-card row', () => {
    const html = render()
    const estatePanel = html.match(/aria-label="Estate progress funnel"[\s\S]*?data-accordion="estate-composition"/)?.[0]
    expect(estatePanel).toBeTruthy()
    expect(estatePanel).not.toContain('class="metrics"')
    for (const label of ['Discovered', 'Eligible', 'Assessed', 'Remediated']) {
      expect(html).toContain(label)
    }
  })
})

describe('every headline number is read from an authority the screen already trusts', () => {
  it('passes the recorded inventory and analysed count to the one estate summary', () => {
    expect(src).toMatch(/reconcileBuckets\(run\?\.scope\?\.inventory, reconciliationInputs\(run, files\)\)/)
    expect(src).toMatch(/<EstateProgressPanel[\s\S]{0,400}inventory=\{run\.scope\?\.inventory\}/)
    expect(src).toMatch(/<EstateProgressPanel[\s\S]{0,400}analysed=\{analysed\}/)
  })

  it('takes findings from assessMetrics, the module the Assess tab uses', () => {
    // One run must not report two different findings totals depending on which tab you stand on.
    // assessMetrics is imported from the shared module (alongside the coverage/severity helpers the
    // organic Overview's assessment section reuses) — the point is that the findings total comes from
    // there, not that it is the only named import.
    expect(src).toMatch(/import \{ assessMetrics[^}]*\} from '\.\/assessMetrics\.js'/)
    expect(src).toMatch(/assessMetrics\(files, \{ cap, assessment \}\)/)
  })

  it('derives no headline number of its own', () => {
    // The metrics row reads values; it does not compute them. A headline that starts doing its own
    // arithmetic is how the four-denominator defect came back last time.
    const row = src.slice(src.indexOf('<div className="metrics">'), src.indexOf('</div>', src.indexOf('<div className="metrics">') + 400))
    expect(row).not.toMatch(/Math\.round|\/ n|\* 100|\.filter\(|\.reduce\(/)
  })
})

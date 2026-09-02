import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import Overview from './Overview.jsx'

// The Overview's four headline tiles (approved board 7) — REMOVED on 2026-09-02 by the PRD "ACP
// Discover and Overview Simplification". EstateProgressPanel's KPI cards (discovered / eligible /
// assessed / remediated) are the headline row now, and they are not inside a disclosure: the
// primary KPI summary stays visible on load.
//
// This file is kept, and rewritten to pin the removal, because the tiles were removed once before
// for being the WRONG four — `documents` counted the scan's file ROWS while the panel beneath it
// partitioned the DISCOVERED estate, and `certifiable` / `audit-ready` are the score #545 removed
// from Assess in other clothes. This screen exports as the compliance report, so a removed verdict
// creeping back in as a tile matters more than it looks. The invariants below are therefore stated
// against whatever renders the headline today.

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

// The KPI cards are `<span>label</span>...<b>value</b>` inside one `.metric`; this reads the value
// beside a given label. Returns null when no card carries that label at all, which is how the
// removed tiles are told apart from a card rendering the wrong number.
const kpiValue = (html, label) => {
  const m = html.match(new RegExp(`<span[^>]*>${label}</span><b[^>]*>([^<]*)</b>`))
  return m ? m[1] : null
}

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

describe('the KPI row that replaced them keeps the invariants the tiles were fixed for', () => {
  it('counts the DISCOVERED estate, not the scanrows', () => {
    // 12,408 discovered vs 2 file rows. The old `documents` tile printed the latter while the
    // panel below partitioned the former — one screen disagreeing with itself.
    expect(kpiValue(render(), 'discovered')).toBe('12,408')
  })

  it('renders an em dash, never a zero, when a KPI has no measurement', () => {
    // No inventory: the discovered and eligible totals are unknown. A "0" here would assert that
    // discovery found nothing, which is a result nobody obtained.
    const html = render({ run: { ...RUN, scope: { kind: 'drive' } } })
    expect(kpiValue(html, 'discovered')).toBe('—')
    expect(kpiValue(html, 'eligible')).toBe('—')
  })

  it('reports a measured KPI as its number rather than blanking it', () => {
    // The em-dash rule must not swallow a real measurement — otherwise the test above would pass
    // on a component that renders a dash unconditionally. `toBe`, not `not.toBe`: a label that has
    // stopped rendering reads as null, and `null !== '—'` would let that pass silently.
    expect(kpiValue(render(), 'assessed')).toBe('2')
    expect(kpiValue(render(), 'eligible')).toBe('9,000')
  })

  it('is not hidden behind a disclosure — the primary KPI summary is visible on load', () => {
    // Overview's detail sections are accordions since 2026-09-02 and several start closed. The KPI
    // row is deliberately not one of them: a dashboard whose headline numbers need a click first
    // is the failure this PRD was meant to remove, not create.
    const html = render()
    expect(html).toMatch(/<span[^>]*>discovered<\/span>/)
    const kpiAt = html.indexOf('>discovered<')
    const firstPanel = html.indexOf('class="acc-panel"')
    expect(kpiAt).toBeGreaterThan(-1)
    // There ARE accordions on this screen — otherwise the ordering below proves nothing.
    expect(firstPanel).toBeGreaterThan(-1)
    expect(kpiAt).toBeLessThan(firstPanel)
  })
})

describe('every headline number is read from an authority the screen already trusts', () => {
  it('takes discovered and assessed from the same call the reconciliation makes', () => {
    // Not a second derivation: reconcileBuckets(inv, reconciliationInputs(run, files)) is exactly
    // what AssessmentReconciliation computes, so the tiles and the partition explaining them are
    // one computation and cannot disagree.
    expect(src).toMatch(/reconcileBuckets\(run\?\.scope\?\.inventory, reconciliationInputs\(run, files\)\)/)
    expect(src).toMatch(/rows\.find\(\(r\) => r\.key === 'assessed'\)/)
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

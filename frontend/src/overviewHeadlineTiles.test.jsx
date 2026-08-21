import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import Overview from './Overview.jsx'

// The Overview's four headline tiles (approved board 7).
//
// The screen already had four, and they were the wrong four: `documents` counted the scan's file
// ROWS while the panel directly beneath it partitions the DISCOVERED estate, and `certifiable` /
// `audit-ready` are the score in other clothes — the verdict #545 removed from Assess because
// severity weighting cannot tell "checked and passed" from "not checked".
//
// This screen exports as the compliance report, which is why a removed verdict surviving here
// would matter more than it looks.

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

// The tiles are `<span>label</span><b>value</b>`; this reads the value that follows a given label.
const tileValue = (html, label) => {
  const m = html.match(new RegExp(`<span>${label}</span><b[^>]*>([^<]*)</b>`))
  return m ? m[1] : null
}

describe('the four headline tiles the board specifies', () => {
  it('renders all four labels', () => {
    const html = render()
    for (const label of ['files discovered', 'assessed against WCAG', 'documents need action', 'findings']) {
      expect(html).toContain(`<span>${label}</span>`)
    }
  })

  it('counts the DISCOVERED estate, not the scanrows', () => {
    // 12,408 discovered vs 2 file rows. The old `documents` tile printed the latter while the
    // reconciliation below partitioned the former — one screen disagreeing with itself.
    expect(tileValue(render(), 'files discovered')).toBe('12,408')
  })

  it('drops certifiable and audit-ready, which are the removed score in other clothes', () => {
    const html = render()
    expect(html).not.toContain('<span>certifiable</span>')
    expect(html).not.toContain('<span>audit-ready</span>')
    // and the old row-count tile
    expect(html).not.toContain('<span>documents</span>')
  })

  it('renders an em dash, never a zero, when a tile has no measurement', () => {
    // No inventory: the discovered and assessed totals are unknown. A "0" here would assert that
    // discovery found nothing, which is a result nobody obtained.
    const html = render({ run: { ...RUN, scope: { kind: 'drive' } } })
    expect(tileValue(html, 'files discovered')).toBe('—')
    expect(tileValue(html, 'assessed against WCAG')).toBe('—')
  })

  it('reports findings for an assessed estate rather than blanking them', () => {
    // The em-dash rule must not swallow a real measurement — otherwise the test above would pass
    // on a component that renders a dash unconditionally.
    const html = render()
    expect(tileValue(html, 'findings')).not.toBe('—')
    expect(tileValue(html, 'documents need action')).not.toBe('—')
  })
})

describe('every tile is read from an authority the screen already trusts', () => {
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
    // The tile row reads values; it does not compute them. A tile that starts doing its own
    // arithmetic is how the four-denominator defect came back last time.
    const row = src.slice(src.indexOf('<div className="metrics">'), src.indexOf('</div>', src.indexOf('<div className="metrics">') + 400))
    expect(row).not.toMatch(/Math\.round|\/ n|\* 100|\.filter\(|\.reduce\(/)
  })
})

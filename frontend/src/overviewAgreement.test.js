import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { statusSegments, severityItems } from './charts.jsx'
import { statusOf, analysedCount } from './docStatus.js'
import { recommendFor, remediableCount, REMEDIATION_ACTIONS } from './sim.js'

const here = dirname(fileURLToPath(import.meta.url))
const overviewSrc = readFileSync(join(here, 'Overview.jsx'), 'utf8')

// Observed live on 2026-07-29 against v2026.7.29.2, scope "Full estate · all departments":
//
//     documents          258
//     certifiable        (BLANK — no number rendered at all)
//     need remediation   258
//     audit-ready        0%
//     donut              258 documents · "issues 258"
//     severity           "No open findings."
//
// Reproduced from the API side by driving api/store.py directly: init_scan_run(total=258) +
// add_inventory(258) + cancel_scan() — the shape below is the VERBATIM row GET /scans/{id}
// returned for that scan, before the fix. Nothing about it is invented; every field is what
// the inventory fallback (ADR 0020) writes for a document that was listed but never opened.
const unopenedDoc = (i) => ({
  file: `dept-doc-${String(i).padStart(3, '0')}.pdf`,
  engine: 'pdf',
  status: 'discovered',
  score: null,
  compliant: 0,
  skipped_rules: 0,
  remediated_at: null,
  drive_write_url: null,
  acp_stamped: null,
  published_at: null,
  size_kb: 120 + i,
  pages: null,
  sheets: null,
  drive_file_id: null,
  sourceName: 'Google Drive',
  issues: [],
})

// App.jsx:287 — a real backend file arrives without `rec`, so the app computes one here.
const asApp = (files) => files.map((f) => (f.rec ? f : { ...f, rec: recommendFor(f) }))

const CANCELLED_258 = {
  // Post-fix the counters are derived rather than NULL (api/store.py _fill_run_aggregate);
  // the `null` variants are covered separately below so a regression on either side is caught.
  run: { id: 'repro258', status: 'cancelled', files: 258, certifiable: 0, uncertain: 0, error: 0, avg_score: null },
  files: asApp(Array.from({ length: 258 }, (_, i) => unopenedDoc(i))),
}

describe('the Overview panels cannot contradict each other', () => {
  // THE reported bug, stated as an invariant rather than as six numbers. "Needs remediation"
  // and "has an open finding" must describe the same documents, because the remediation tile
  // and the severity panel read the same `files` array and claim to describe the same estate.
  it('never counts a document as needing remediation unless it has an open finding', () => {
    const { files } = CANCELLED_258
    const needFix = remediableCount(files)
    const withFindings = files.filter((f) => (f.issues || []).length).length

    expect(needFix).toBe(0)
    expect(severityItems(files)).toEqual([])
    // The general rule, not just this scan: the backlog can never exceed the documents that
    // actually have something to fix.
    expect(needFix).toBeLessThanOrEqual(withFindings)
  })

  it('puts zero-finding documents in the donut bucket that means zero findings', () => {
    const { run, files } = CANCELLED_258
    const segs = statusSegments(run, files)
    const by = Object.fromEntries(segs.map((s) => [s.label, s.value]))

    // Pre-fix this read `issues: 258` — every document, by subtraction, with no finding behind it.
    expect(by.issues).toBeUndefined()
    expect(by.clean).toBe(258)
  })

  // The donut is clickable: Overview's pickStatus opens `files.filter(f => statusOf(f) === label)`.
  // A segment whose count disagrees with the list it opens is the same defect wearing a
  // different hat — pre-fix, clicking "issues 258" opened an empty drawer.
  it('gives every donut segment the same count as the drill-in it opens', () => {
    const { run, files } = CANCELLED_258
    for (const seg of statusSegments(run, files)) {
      expect(files.filter((f) => statusOf(f) === seg.label).length).toBe(seg.value)
    }
  })

  it('accounts for every document exactly once', () => {
    const { run, files } = CANCELLED_258
    const total = statusSegments(run, files).reduce((a, s) => a + s.value, 0)
    expect(total).toBe(files.length)
  })
})

// The counters were NULL because the scan never reached finalize_scan_run. api/store.py now
// derives them at read, but the chart must not depend on that having happened: `null` coerces
// to 0 in arithmetic and the old subtraction turned that into "the entire estate has issues".
describe('statusSegments does not do arithmetic on absent run counters', () => {
  const nullRun = { id: 'x', files: 258, certifiable: null, uncertain: null, error: null, avg_score: null }

  it('reports no issues when a null-countered run holds only zero-finding documents', () => {
    const files = asApp(Array.from({ length: 258 }, (_, i) => unopenedDoc(i)))
    const segs = statusSegments(nullRun, files)
    expect(segs.find((s) => s.label === 'issues')).toBeUndefined()
    expect(segs.find((s) => s.label === 'clean').value).toBe(258)
  })

  it('still counts the real buckets from a mixed estate', () => {
    const files = asApp([
      { ...unopenedDoc(1), status: 'analysed', compliant: 1, score: 100 },
      { ...unopenedDoc(2), status: 'analysed', compliant: 0, score: 61, issues: [{ wcag: 'SC_1_1_1', severity: 'SERIOUS' }] },
      { ...unopenedDoc(3), status: 'uncertain', compliant: 0, score: 84 },
      { ...unopenedDoc(4), status: 'error', compliant: 0 },
      { ...unopenedDoc(5), status: 'analysed', compliant: 0, score: 100 },  // assessed, nothing failed
    ])
    const by = Object.fromEntries(statusSegments(nullRun, files).map((s) => [s.label, s.value]))
    expect(by).toEqual({ certifiable: 1, issues: 1, clean: 1, uncertain: 1, unanalysable: 1 })
  })
})

describe('recommendFor — no findings means no remediation action', () => {
  const rec = (f) => recommendFor({ status: 'analysed', compliant: 0, issues: [], score: 100, ...f })

  it('does not route a zero-finding document into the remediation backlog', () => {
    for (const f of [
      { status: 'discovered', score: null },        // ADR 0020 inventory row — never opened
      { status: 'analysed', score: 100 },           // assessed, no rule failed
      { status: 'skipped', score: null },
    ]) {
      expect(REMEDIATION_ACTIONS).not.toContain(rec(f).action)
    }
  })

  it('never narrates a fix for findings that do not exist', () => {
    // The tell that made this visible: "All 0 findings are mechanical … No human needed."
    expect(rec({ status: 'analysed', score: 100 }).rationale).not.toMatch(/\b0 findings?\b/)
    expect(rec({ status: 'discovered', score: null }).rationale).toMatch(/not assessed/i)
  })

  it('costs no effort, because there is no work to do', () => {
    expect(rec({}).etaMin).toBe(0)
  })

  it('still routes a document that DOES have findings', () => {
    const r = recommendFor({ status: 'analysed', compliant: 0, score: 55, type: 'html',
                             issues: [{ wcag: 'SC_1_1_1', severity: 'SERIOUS' }] })
    expect(REMEDIATION_ACTIONS).toContain(r.action)
  })

  it('leaves the verdicts that were already right alone', () => {
    expect(recommendFor({ status: 'error', compliant: 0, issues: [] }).action).toBe('manual')
    expect(recommendFor({ status: 'uncertain', compliant: 0, issues: [], skipped_rules: 2 }).action).toBe('review')
    expect(recommendFor({ status: 'analysed', compliant: 1, issues: [], score: 100 }).action).toBe('keep')
  })
})

describe('analysedCount separates documents we opened from documents we merely listed', () => {
  it('counts only the analysed ones', () => {
    const files = [unopenedDoc(1), unopenedDoc(2), { ...unopenedDoc(3), status: 'analysed', score: 90 }]
    expect(analysedCount(files)).toBe(1)
  })
})

// A rate over an estate nobody analysed is not 0% — it is unknown. "0% audit-ready" asserts
// that all 258 documents were checked and none passed, which is a stronger claim than the data
// supports, and a blank tile is not an improvement on it.
describe('Overview reports absent values as absent, not as zero', () => {
  it('renders an em dash for certifiable rather than nothing at all', () => {
    expect(overviewSrc).toMatch(/certifiable<\/span><b[^>]*>\{run\.certifiable \?\? '—'\}/)
  })

  it('computes audit-ready only when something was actually analysed', () => {
    expect(overviewSrc).toMatch(/const auditReady = \(analysed && n && run\.certifiable != null\)/)
    expect(overviewSrc).toMatch(/const auditReadyLabel = auditReady == null \? '—'/)
  })

  it('states the scope on screen when part of the estate was never analysed', () => {
    expect(overviewSrc).toMatch(/analysed < n && \(/)
    expect(overviewSrc).toMatch(/have been analysed/)
  })

  it('derives the open-findings insight by counting documents, not by subtracting counters', () => {
    expect(overviewSrc).toMatch(/const issuesOnly = files\.filter\(\(f\) => statusOf\(f\) === 'issues'\)\.length/)
    expect(overviewSrc).not.toMatch(/n - run\.certifiable - run\.uncertain - run\.error/)
  })
})

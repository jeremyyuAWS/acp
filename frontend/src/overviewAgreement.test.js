import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { statusSegments, severityItems, Bars } from './charts.jsx'
import { statusOf, statusCounts, analysedCount, avgScore, ALL_STATUSES, NOT_ASSESSED } from './docStatus.js'
import { recommendFor, remediableCount, REMEDIATION_ACTIONS } from './sim.js'

const here = dirname(fileURLToPath(import.meta.url))
const overviewSrc = readFileSync(join(here, 'Overview.jsx'), 'utf8')
const SHARED_STATUS_CONSUMERS = ['Dashboard.jsx', 'charts.jsx', 'scanReport.js', 'FileDrawer.jsx']

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

  it('puts unopened documents in the donut bucket that means nobody measured them', () => {
    const { run, files } = CANCELLED_258
    const segs = statusSegments(run, files)
    const by = Object.fromEntries(segs.map((s) => [s.label, s.value]))

    // Pre-fix this read `issues: 258` — every document, by subtraction, with no finding behind it.
    expect(by.issues).toBeUndefined()
    // …and the first fix moved them into 'clean', which is the OTHER wrong answer: these 258 were
    // listed and never opened, so "no findings" asserts a measurement that never happened.
    expect(by.clean).toBeUndefined()
    expect(by[NOT_ASSESSED]).toBe(258)
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

  it('reports no issues when a null-countered run holds only unopened documents', () => {
    const files = asApp(Array.from({ length: 258 }, (_, i) => unopenedDoc(i)))
    const segs = statusSegments(nullRun, files)
    expect(segs.find((s) => s.label === 'issues')).toBeUndefined()
    expect(segs.find((s) => s.label === 'clean')).toBeUndefined()
    expect(segs.find((s) => s.label === NOT_ASSESSED).value).toBe(258)
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

// There were three verbatim copies of this verdict — FileDrawer.jsx, Dashboard.jsx and
// scanReport.js — each commented "mirrors FileDrawer's statusOf". A mirror is exactly what
// fails silently: nothing makes a copy follow the original when it changes, and a dashboard
// whose panels each hold their own definition of "does this document have findings" is one
// edit away from disagreeing with itself again. One definition, imported everywhere.
describe('the document verdict has exactly one definition', () => {
  it('is not re-declared by any consumer', () => {
    for (const f of SHARED_STATUS_CONSUMERS) {
      const src = readFileSync(join(here, f), 'utf8')
      expect(src, `${f} re-declares statusOf instead of importing it`)
        .not.toMatch(/^\s*(const|function|export const|export function)\s+statusOf\b/m)
    }
  })

  it('is imported from the shared module by every consumer', () => {
    for (const f of SHARED_STATUS_CONSUMERS.filter((x) => x !== 'FileDrawer.jsx')) {
      const src = readFileSync(join(here, f), 'utf8')
      // `statusOf` OR `statusCounts` — the latter is the shared per-verdict counter, defined in
      // docStatus.js in terms of statusOf, and is what a consumer that only ever tallies files
      // (charts.jsx) should import. Requiring the raw predicate by name would have that module
      // hold a dead import purely to satisfy this test. What must not happen — a consumer
      // declaring its own verdict — is the assertion above.
      expect(src, `${f} does not import the shared verdict from docStatus.js`)
        .toMatch(/import \{[^}]*\b(statusOf|statusCounts)\b[^}]*\} from '\.\/docStatus\.js'/)
    }
  })

  // Dashboard held a verbatim copy of the badge PALETTE too. That is the same failure a step
  // later: a verdict added to docStatus.js renders with `BADGE[st]` undefined, and the row throws
  // on destructuring instead of showing the new state.
  it('is not re-coloured by any consumer holding its own badge map', () => {
    for (const f of SHARED_STATUS_CONSUMERS) {
      const src = readFileSync(join(here, f), 'utf8')
      expect(src, `${f} declares its own status badge map instead of importing STATUS_BADGE`)
        .not.toMatch(/^\s*(const|export const)\s+(BADGE|STATUS_BADGE)\s*=\s*\{/m)
    }
  })
})

// The hero counters and the rows beneath them read the same estate, so they cannot disagree about
// how many documents have findings. Reported live 2026-07-30:
//
//     MASTER SCORE  0 certifiable · 2 issues · 0 uncertain · 0 unanalysable · 2 files
//     rows          both "clean", both "score: n/a", both "findings: clean"
//
// "2 issues" came from `run.files - run.certifiable - run.uncertain - run.error` — the same
// subtraction #77 removed from statusSegments and left in Dashboard's hero. With five verdicts
// and four tiles, everything unnamed landed in "issues" by elimination.
describe('the Dashboard hero counters agree with the inventory rows', () => {
  const dashSrc = readFileSync(join(here, 'Dashboard.jsx'), 'utf8')

  it('counts documents instead of subtracting counters', () => {
    expect(dashSrc).not.toMatch(/run\.files - run\.certifiable - run\.uncertain - run\.error/)
    expect(dashSrc).toMatch(/countStatuses\(files\)/)
  })

  it('never reports issues over an estate whose rows all say otherwise', () => {
    const { files } = CANCELLED_258
    const counts = statusCounts(files)
    const rowsWithFindings = files.filter((f) => (f.issues || []).length).length

    expect(counts.issues).toBe(0)
    expect(counts.issues).toBeLessThanOrEqual(rowsWithFindings)
    expect(counts[NOT_ASSESSED]).toBe(258)
  })

  it('has a tile for every verdict, so no document can be absorbed into a bucket', () => {
    for (const st of ALL_STATUSES) {
      expect(Object.keys(statusCounts([])), `no counter bucket for '${st}'`).toContain(st)
    }
    // The tiles rendered on screen cover the same partition — a verdict with no tile is a
    // document whose count is simply not shown, which is how the subtraction hid them before.
    for (const st of ALL_STATUSES) {
      expect(dashSrc, `Dashboard has no hero tile for '${st}'`)
        .toMatch(st === NOT_ASSESSED ? /NOT_ASSESSED, 'not assessed'/ : new RegExp(`'${st}'`))
    }
  })

  it('sums the tiles to the file count exactly', () => {
    const files = asApp([
      { ...unopenedDoc(1), status: 'analysed', compliant: 1, score: 100 },
      { ...unopenedDoc(2), status: 'analysed', compliant: 0, score: 61, issues: [{ wcag: 'SC_1_1_1', severity: 'SERIOUS' }] },
      { ...unopenedDoc(3), status: 'uncertain', compliant: 0, score: 84 },
      { ...unopenedDoc(4), status: 'error', compliant: 0 },
      { ...unopenedDoc(5), status: 'analysed', compliant: 0, score: 100 },
      unopenedDoc(6),
    ])
    const counts = statusCounts(files)
    expect(Object.values(counts).reduce((a, n) => a + n, 0)).toBe(files.length)
    expect(counts).toEqual({ certifiable: 1, issues: 1, clean: 1, [NOT_ASSESSED]: 1,
                             uncertain: 1, unanalysable: 1 })
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

// Same defect as the blank `certifiable` tile and "0% audit-ready", one panel over. On the same
// cancelled 258-document scan, "Average score by department" read "Finance 0", "Human Resources
// 0", … — a failing grade, on a /100 scale, for documents that were listed and never opened.
// 0/100 is a measurement; an unopened inventory row has none.
describe('an average over nothing is absent, not zero', () => {
  const scored = (i, score) => ({ ...unopenedDoc(i), status: 'analysed', score })

  it('returns null when no document in the group was scored', () => {
    expect(avgScore(CANCELLED_258.files)).toBeNull()
    expect(avgScore([])).toBeNull()
    expect(avgScore(undefined)).toBeNull()
  })

  it('averages only the scored documents, ignoring the unscored ones', () => {
    // 90 and 70 average to 80. The two unopened rows must not drag it toward zero, and must
    // not count in the denominator either — that was the other way to get a wrong number here.
    expect(avgScore([scored(1, 90), scored(2, 70), unopenedDoc(3), unopenedDoc(4)])).toBe(80)
  })

  it('is the same function scanReport uses, not a second copy', () => {
    // scanReport's avgOf already returned null; Overview's copy returned 0. Two definitions of
    // one average is how they came to disagree, so neither file may re-declare it.
    for (const f of ['Overview.jsx', 'scanReport.js']) {
      const src = readFileSync(join(here, f), 'utf8')
      // A DEFINITION, not a use — `const avgScore = avgOf(files)` in scanReport is the report
      // model's field, which is fine. What must not come back is a second implementation.
      expect(/\b(avgScore|avgOf)\s*=\s*\([^)]*\)\s*=>/.test(src), `${f} redefines the average as an arrow function`).toBe(false)
      expect(/function\s+(avgScore|avgOf)\s*\(/.test(src), `${f} redefines the average as a function`).toBe(false)
      expect(src, `${f} does not import avgScore from docStatus.js`)
        .toMatch(/import \{[^}]*\bavgScore\b[^}]*\} from '\.\/docStatus\.js'/)
    }
  })
})

// A null has to survive the trip to the screen. Returning null from avgScore and then rendering
// it as `{it.value}` (nothing at all) or `${it.value}/100` ("null/100") is the same class of
// defect one layer down — the blank `certifiable` tile was exactly that.
describe('an unmeasured group renders as absent all the way to the bar', () => {
  const barsSrc = readFileSync(join(here, 'charts.jsx'), 'utf8')
  // Rendered, not grepped — the bug was what reached the screen. Read the VALUE CELL's own
  // text, not the whole markup: the row also carries an explanatory title attribute containing
  // an em dash, so a substring check on the html passes even when the cell renders empty.
  const cellText = (value) => {
    const html = renderToStaticMarkup(createElement(Bars, { items: [{ label: 'Finance', value, color: '#9a948f' }], max: 100 }))
    const m = html.match(/<span class="critn"[^>]*>([^<]*)<\/span>/)
    return m ? m[1] : null
  }

  it('shows an em dash, not a number, for a group with no score', () => {
    // Pre-fix this cell read "0". Rendering `{null}` instead is no better — that is the blank
    // `certifiable` tile, which is the defect this panel's sibling was just fixed for.
    expect(cellText(null)).toBe('—')
  })

  it('still renders a real average unchanged', () => {
    expect(cellText(74)).toBe('74')
  })

  it('renders a genuine measured zero as 0, not as absent', () => {
    // The distinction the whole fix rests on: a department that WAS analysed and scored 0 is a
    // real measurement and must still read "0". Only null is unknown.
    expect(cellText(0)).toBe('0')
  })

  it('leaves no bar to fill for an unmeasured group', () => {
    expect(barsSrc).toMatch(/width: on && !absent \?/)
  })

  it('colours an unmeasured group neutral, never a score band', () => {
    // scoreColor's fallback used to be the "below 50 · at risk" blue, so an unanalysed
    // department was painted with the worst band on the chart.
    expect(overviewSrc).toMatch(/const scoreColor = \(s\) => s == null \? NA_GREY/)
  })

  it('never interpolates a null score into a drill-in title', () => {
    // Pre-fix both score panels opened a drawer headed "Finance · avg 0 / 100". The score may
    // still be interpolated — but only on the branch that has established it is not null.
    expect(/title: `\$\{it\.label\}[^`]*· avg/.test(overviewSrc), 'a drill-in title interpolates the score with no null guard').toBe(false)
    expect(overviewSrc).toMatch(/it\.value == null \? `\$\{it\.label\} · not yet scored`/)
    expect(overviewSrc).toMatch(/it\.value == null \? `\$\{it\.label\}-owned · not yet scored`/)
  })

  it('does not name a lowest-scoring department when none has a score', () => {
    // The insight sentence ranked scoreByDept[0] unconditionally: with every group at 0 it
    // announced an arbitrary department as "the highest-leverage starting point".
    expect(overviewSrc).toMatch(/const deptRanked = scoreByDept\.filter\(\(d\) => d\.value != null\)/)
    expect(overviewSrc).toMatch(/!deptRanked\.length/)
    expect(overviewSrc).not.toMatch(/scoreByDept\[0\]\.value/)
  })

  it('puts unscored groups last in the ranking rather than at the bottom of it', () => {
    expect(overviewSrc).toMatch(/const byScoreAsc = \(a, b\) => \(a\.value == null\) - \(b\.value == null\)/)
  })
})

// The estate PDF drew a 0/100 dial on its cover from `d.avgScore ?? 0` while the summary two
// lines later correctly said "n/a" — the same report contradicting itself on one page.
describe('the estate report omits the score dial it cannot compute', () => {
  const pdfSrc = readFileSync(join(here, 'pdfReport.js'), 'utf8')

  it('guards the ring instead of defaulting it to zero', () => {
    expect(pdfSrc).not.toMatch(/p\.ring\(d\.avgScore \?\? 0/)
    expect(pdfSrc).toMatch(/if \(d\.avgScore != null\) p\.ring\(d\.avgScore/)
  })
})

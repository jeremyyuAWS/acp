import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { statusSegments, severityItems, Bars } from './charts.jsx'
import Overview from './Overview.jsx'
import { mountExpanded } from './testAccordion.js'
import { findingsByCriterion, findingsByLevel, levelOfFinding } from './wcagFinding.js'
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
  it('renders an em dash for an unmeasured KPI rather than a zero', () => {
    // The four headline tiles were removed from Overview on 2026-09-02 (PRD "ACP Discover and
    // Overview Simplification"); EstateProgressPanel's KPI cards are the headline now. The
    // INVARIANT is the reason this test exists and is unchanged: an absent measurement must not
    // render as a measured zero. It moved from Overview's `tile()` helper to KpiCard.
    expect(overviewSrc).not.toMatch(/<span>files discovered<\/span>/)
    const panel = readFileSync(join(here, 'EstateProgressPanel.jsx'), 'utf8')
    expect(panel).toMatch(/\{value == null \? '—' : nf\.format\(value\)\}/)
    // A null KPI reaches the screen as the dash, not as 0.
    expect(screen({ ...SCAN_12F2_RUN, certifiable: null, scope: { kind: 'drive' } }, []))
      .not.toMatch(/discovered 0 total estate/)
  })

  it('computes audit-ready only when something was actually analysed', () => {
    expect(overviewSrc).toMatch(/const auditReady = \(analysed && n && run\.certifiable != null\)/)
    expect(overviewSrc).toMatch(/const auditReadyLabel = auditReady == null \? '—'/)
  })

  it('states the assessed-vs-eligible scope on screen rather than implying full coverage', () => {
    // The "N of M documents have been analysed" banner went with the headline tiles on
    // 2026-09-02. The claim it made is still made, by the coverage sentence in the Assessment
    // section's own heading — which is derived from assessMetrics, not from a second count.
    expect(overviewSrc).toMatch(/meta=\{coverageSentence\(metrics\)\}/)
    const am = readFileSync(join(here, 'assessMetrics.js'), 'utf8')
    expect(am).toMatch(/export function coverageSentence/)
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
    // The by-department / by-seniority score panels and the drawers they opened were removed from
    // Overview on 2026-09-02, so there is no such title left to get wrong. What must not come back
    // is the shape of the defect: a score interpolated on a branch that has not established it is
    // not null. Pinned against the source so a restored panel cannot restore the bug with it.
    expect(/title: `\$\{it\.label\}[^`]*· avg/.test(overviewSrc), 'a drill-in title interpolates the score with no null guard').toBe(false)
    expect(overviewSrc).not.toMatch(/Average score by department/)
    expect(overviewSrc).not.toMatch(/Average score by owner seniority/)
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

// ── 2026-07-30, acp-app:598abe9 (v2026.7.30.3), scan 12f28938cd2f ────────────────────────────
//
// A whole-Drive scan: 8 files listed, 4 kept. One of the 4 was a remediated .docx ACP had
// written back to Drive under the source document's own name, so `get_scan` dropped it from the
// file list (shadowed_acp_outputs — an artifact is not a document in the estate) while the
// scan_runs counters still counted it. The Overview then showed, all at once:
//
//     documents 4 · certifiable 3 · audit-ready 75%
//     [donut] 3 documents — 2 certifiable, 1 issues
//     Scope: 3 of 4 documents have been analysed — the rest were discovered but not yet assessed.
//     Findings by severity: moderate 6        Findings by WCAG level: "No open findings."
//     Top WCAG violations: "Info and Relationships" AND "info & relationships"
//
// and Discover, reading the same file list, said 3 documents.
//
// The rows below are that scan's, verbatim: two passing PDFs, one .docx failing at 68, and the
// ACP copy of that .docx — stamped, passing at 92 — which is the row the counters could see and
// the list could not. Findings carry the wcag spellings the three writers actually emit and no
// `level` field, because real scan findings have none.
const ROI_SOURCE = 'HIM_ROI_Instructions_06.02.2025 (1).docx'
const driveDoc = (file, over = {}) => ({
  file, engine: 'python/pdf', status: 'analysed', score: 92, compliant: 1, skipped_rules: 0,
  remediated_at: null, drive_write_url: null, acp_stamped: null, published_at: null,
  sourceName: 'Google Drive', issues: [], ...over,
})
const SCAN_12F2_FILES = asApp([
  driveDoc('authorization-to-disclose-phi-english-2026-04.pdf', { issues: [
    { rule_id: 'OCR_IMAGE_OF_TEXT_STRICT', wcag: '1.4.9 Images of Text (No Exception)', severity: 'MODERATE' },
    { rule_id: 'PDF_TIGHT_LINE_SPACING', wcag: '1.4.12 Text Spacing', severity: 'REVIEW' },
    { rule_id: 'PDF_NONTEXT_LOW_CONTRAST', wcag: '1.4.11 Non-text Contrast', severity: 'REVIEW' },
  ] }),
  driveDoc(ROI_SOURCE, { engine: '.net/office', score: 68, compliant: 0, issues: [
    { rule_id: 'DOCX-HEAD-001', wcag: 'SC_1_3_1', severity: 'MODERATE' },
    { rule_id: 'DOCX-HEAD-001', wcag: 'SC_1_3_1', severity: 'MODERATE' },
    { rule_id: 'OCR_IMAGE_OF_TEXT_STRICT', wcag: '1.4.9 Images of Text (No Exception)', severity: 'MODERATE' },
    { rule_id: 'DOCX_PSEUDO_HEADING', wcag: '1.3.1 Info and Relationships', severity: 'MODERATE' },
  ] }),
  driveDoc('HIM_ROI_Instructions_06.02.2025.pdf', { issues: [
    { rule_id: 'OCR_IMAGE_OF_TEXT_STRICT', wcag: '1.4.9 Images of Text (No Exception)', severity: 'MODERATE' },
    { rule_id: 'PDF_NONTEXT_LOW_CONTRAST', wcag: '1.4.11 Non-text Contrast', severity: 'REVIEW' },
  ] }),
])
// What api/store.py hands out once the counters are reconciled with the list (its own tests pin
// the derivation; this pins what the screen does with the result).
const SCAN_12F2_RUN = {
  id: '12f28938cd2f', status: 'done', source: 'drive', files: 3, certifiable: 2, uncertain: 0,
  error: 0, avg_score: 84, assessed_at: '2026-07-30T14:31:00Z',
  scope: { kind: 'drive', raw: 8, scannable: 4, skipped_acp: 0, kept: 4, truncated: false, cap: 2500 },
}
// Overview's sections are disclosures since the 2026-09-02 UI-simplification PRD, and several
// start closed — a closed one renders no children, so a static render would assert on markup that
// is not there. Mount it and open every section through its own header button, then read the text.
const screen = (run = SCAN_12F2_RUN, files = SCAN_12F2_FILES) =>
  mountExpanded(createElement(Overview, {
    run, files, trend: [], trendDates: [], onGo: () => {}, scanList: [], onPickScan: () => {},
    me: { email: 'auditor@example.com' },
  })).textContent.replace(/\s+/g, ' ')

describe('the Overview totals count the documents the Overview lists', () => {
  it('does not report more documents than the estate it is describing', () => {
    // The four tiles, the donut, the funnel and the score bands are six answers to "how many
    // documents"; they came from two different populations.
    const html = screen()
    // The four tiles were removed on 2026-09-02. This run's scope carries no inventory, so the
    // estate KPIs have nothing to report — and report a dash, rather than claiming discovery
    // found 0 documents.
    expect(html).toMatch(/discovered—/)
    expect(html).not.toMatch(/discovered0/)
    // The invariant this test was written for is the line below, and it is untouched: the
    // funnel and the KPI row must all describe ONE population.
    expect(statusSegments(SCAN_12F2_RUN, SCAN_12F2_FILES).reduce((a, s) => a + s.value, 0))
      .toBe(SCAN_12F2_RUN.files)
  })

  it('shows no partial-analysis banner when nothing is missing', () => {
    // `analysed < n` printed "the rest were discovered but not yet assessed" over a document
    // that HAD been assessed (score 92) and was simply not a source document — a true-sounding
    // sentence covering for a number that was wrong.
    expect(analysedCount(SCAN_12F2_FILES)).toBe(SCAN_12F2_RUN.files)
    expect(screen()).not.toMatch(/discovered but not yet assessed/)
  })

  it('still explains a genuine gap, so the coverage claim is not merely silenced', () => {
    // The wording moved with the panel: the "N of M documents have been analysed" banner is gone,
    // and the Assessment heading's coverage sentence carries the same fact. What matters is that
    // a partly-analysed estate still SAYS it is partly analysed somewhere a reader will see.
    const partial = [...SCAN_12F2_FILES, asApp([driveDoc('never-opened.pdf',
      { status: 'discovered', score: null, compliant: 0 })])[0]]
    const html = screen({ ...SCAN_12F2_RUN, files: 4 }, partial)
    expect(html).toMatch(/4,?\s*not eligible|awaiting assessment|of eligible|of discovered/)
    expect(html).toMatch(/Assessment/)
  })
})

describe('the Overview says which findings each panel counts', () => {
  it('derives the level split from the criterion, not from a `level` field findings do not carry', () => {
    // The "Findings by WCAG level" panel was removed from Overview on 2026-09-02 (PRD "ACP
    // Discover and Overview Simplification"). The DEFECT it was written for is not about the
    // panel: real findings carry no `level`, so counting `i.level` returned zero and any consumer
    // reading it would report "no findings" over an estate full of them. findingsByLevel is still
    // exported and still used (scanReport, pdfReport), so the invariant is pinned at the source.
    expect(overviewSrc).not.toMatch(/Findings by WCAG level/)
    const lv = findingsByLevel(SCAN_12F2_FILES)
    expect(lv.A).toBe(3)
    expect(lv.AA).toBe(3)
    expect(lv.AAA).toBe(3)
    expect(lv.unknown).toBe(0)
    expect(SCAN_12F2_FILES.every((f) => f.issues.every((i) => i.level == null))).toBe(true)
  })

  it('counts one criterion once, however the finding spelled it', () => {
    // 'SC_1_3_1' (×2, .NET/Office) and '1.3.1 Info and Relationships' (×1, Python) are one
    // criterion. Keyed raw they were two entries in the violations cloud, both 1.3.1, their
    // three findings split 2/1 — so "most common failure" was decided by a spelling. The cloud
    // itself left Overview on 2026-09-02; findingsByCriterion still feeds the exported report,
    // which is where a split criterion would now do its damage.
    expect(findingsByCriterion(SCAN_12F2_FILES).filter((c) => c.sc === '1.3.1'))
      .toEqual([expect.objectContaining({ sc: '1.3.1', count: 3 })])
    const cloud = findingsByCriterion(SCAN_12F2_FILES).map((c) => c.sc)
    expect(new Set(cloud).size).toBe(cloud.length)
  })

  it('accounts for the advisory findings the severity panel leaves out', () => {
    // severityItems buckets the four BLOCKING severities. A review-recommended finding (ADR
    // 0023) has none of them, so 3 of the estate's 9 findings were in no bucket and that total
    // silently disagreed with every other finding count on the screen. The severity panel left
    // Overview on 2026-09-02; severityItems still buckets only the blocking four, so the gap it
    // leaves is still real and is still the thing that must reconcile.
    expect(overviewSrc).not.toMatch(/Findings by severity · blocking findings/)
    expect(severityItems(SCAN_12F2_FILES).find((s) => s.label === 'moderate')?.value).toBe(6)
    expect(SCAN_12F2_FILES.reduce((a, f) => a + f.issues.filter((i) => i.severity === 'REVIEW').length, 0)).toBe(3)
    // The two counts reconcile through a stated difference rather than by accident.
    const bySeverity = severityItems(SCAN_12F2_FILES).reduce((a, s) => a + s.value, 0)
    const byLevel = Object.values(findingsByLevel(SCAN_12F2_FILES)).reduce((a, n) => a + n, 0)
    expect(bySeverity + 3).toBe(byLevel)
  })

  it('never files a criterion under a conformance level it does not have', () => {
    // coreStats.levelOf defaults an unplaceable criterion to 'A'. 1.4.9 is AAA, and the Level A
    // row is captioned "the legal floor" — a default there is an invented legal obligation.
    expect(levelOfFinding({ wcag: '1.4.9 Images of Text (No Exception)' })).toBe('AAA')
    expect(levelOfFinding({ wcag: 'SC_1_3_1' })).toBe('A')
    expect(levelOfFinding({ wcag: 'NOT_A_CRITERION' })).toBe(null)
    expect(findingsByLevel([{ issues: [{ wcag: 'NOT_A_CRITERION' }] }]))
      .toEqual({ A: 0, AA: 0, AAA: 0, unknown: 1 })
  })
})

// ── The same build, the demo estate: scan b5911952d892, folder "UTSW DEMO V2" ────────────────
//
// Reported from the live build 2026-07-30, Overview → "Compliance by dimension", four cards in
// one viewport:
//
//     Average score by department · /100        Clinical 6 · Unassigned 12
//     Average score by owner seniority · /100   (BLANK — no rows, no zero, no empty state)
//     Findings by WCAG level                    "No open findings."
//     Documents by score band                   below 50 · at risk  4
//
// with "Findings by severity: critical 6 · serious 15 · moderate 15" immediately above it.
//
// Which figure is TRUE was settled against the scan itself, not by making the panels agree: the
// four documents score 0, 0, 6 and 37 and carry 38 issue_records between them. The scores and
// the score band are right; "No open findings." was the lie. Its cause is not an open/closed
// filter — there is none — it is that every one of those 38 findings has `level: null`, because
// only SIM's corpus sets that field, so `if (levelC[i.level] != null)` counted nothing.
//
// This estate also spells three criteria two ways at once, which the 12f2 fixture only shows for
// one: SC_1_3_1 ×3 + '1.3.1 Info and Relationships' ×1, SC_2_4_4 ×2 + '2.4.4 Link Purpose (In
// Context)' ×2, SC_1_4_3 ×1 + '1.4.3 Contrast (Minimum)' ×1.
const utswDoc = (file, score, issues) => ({
  file, engine: 'engine', status: 'analysed', score, compliant: 0, skipped_rules: 0,
  remediated_at: null, drive_write_url: null, acp_stamped: null, published_at: null,
  sourceName: 'Google Drive', issues: issues.map(([wcag, severity]) => ({ wcag, severity })),
})
const UTSW_FILES = asApp([
  utswDoc('Sample_NonCompliant_ApptTracker.xlsx', 37, [
    ['SC_2_4_2', 'SERIOUS'], ['SC_1_1_1', 'SERIOUS'], ['SC_2_4_6', 'MODERATE'], ['SC_1_3_1', 'MODERATE']]),
  utswDoc('Sample_NonCompliant_PatientDischarge.docx', 0, [
    ['SC_2_4_2', 'SERIOUS'], ['SC_1_1_1', 'CRITICAL'], ['SC_3_1_1', 'SERIOUS'], ['SC_1_3_1', 'MODERATE'],
    ['SC_1_4_3', 'SERIOUS'], ['SC_2_4_4', 'MODERATE'], ['1.4.3 Contrast (Minimum)', 'SERIOUS'],
    ['1.3.3 Sensory Characteristics', 'MODERATE'], ['1.4.9 Images of Text (No Exception)', 'MODERATE'],
    ['1.3.1 Info and Relationships', 'MODERATE'], ['2.4.4 Link Purpose (In Context)', 'MODERATE'],
    ['SC_1_3_2', 'MODERATE'], ['1.4.1 Use of Color', 'MODERATE']]),
  utswDoc('Sample_NonCompliant_PatientPortalOverview.pptx', 0, [
    ['SC_2_4_2', 'SERIOUS'], ['SC_1_1_1', 'CRITICAL'], ['SC_3_1_1', 'SERIOUS'], ['SC_1_3_1', 'MODERATE'],
    ['SC_2_4_4', 'MODERATE'], ['1.3.3 Sensory Characteristics', 'MODERATE'],
    ['1.4.9 Images of Text (No Exception)', 'MODERATE'], ['2.4.9 Link Purpose (Link Only)', 'MODERATE'],
    ['2.4.4 Link Purpose (In Context)', 'MODERATE'], ['1.4.11 Non-text Contrast', 'REVIEW'],
    ['1.4.6 Contrast (Enhanced)', 'MODERATE'], ['SC_2_4_2', 'SERIOUS'], ['SC_1_1_1', 'CRITICAL']]),
  utswDoc('Sample_Patient Intake Form.pdf', 6, [
    ['SC_2_4_2', 'SERIOUS'], ['SC_1_1_1', 'CRITICAL'], ['SC_3_1_1', 'SERIOUS'], ['SC_2_4_2', 'SERIOUS'],
    ['1.3.3 Sensory Characteristics', 'MODERATE'], ['1.4.9 Images of Text (No Exception)', 'MODERATE'],
    ['2.4.9 Link Purpose (Link Only)', 'MODERATE'], ['SC_1_1_1', 'CRITICAL']]),
])
const UTSW_RUN = {
  id: 'b5911952d892', status: 'done', source: 'drive', files: 4, certifiable: 0, uncertain: 0,
  error: 0, avg_score: 11, assessed_at: '2026-07-30T14:35:47Z',
  scope: { kind: 'folder', folder_name: 'UTSW DEMO V2', listed: 4, skipped_acp: 0, kept: 4, truncated: false },
}

describe('the Compliance-by-dimension cards agree with the estate beside them', () => {
  it('does not say "No open findings" over an estate scoring 11/100', () => {
    // The exact pairing on screen was: four documents below 50, and a panel claiming nothing
    // failed. Both panels were removed on 2026-09-02, so the contradiction has no surface left —
    // but the arithmetic underneath is what made it possible, and that is still live.
    const html = screen(UTSW_RUN, UTSW_FILES)
    expect(html).not.toMatch(/below 50 · at risk/)
    expect(html).not.toMatch(/Findings by WCAG level/)
    const lv = findingsByLevel(UTSW_FILES)
    expect(lv.A + lv.AA + lv.AAA).toBe(UTSW_FILES.reduce((a, f) => a + f.issues.length, 0))
    expect(lv.unknown).toBe(0)
  })

  it('reconciles the level panel with the severity panel through a stated difference', () => {
    const blocking = severityItems(UTSW_FILES).reduce((a, s) => a + s.value, 0)
    const all = Object.values(findingsByLevel(UTSW_FILES)).reduce((a, n) => a + n, 0)
    const advisory = UTSW_FILES.reduce((a, f) => a + f.issues.filter((i) => i.severity === 'REVIEW').length, 0)
    expect(blocking + advisory).toBe(all)
    // The sentence that stated the difference went with the two panels on 2026-09-02. What must
    // not come back is a screen that prints one of these totals as if it were the other.
    expect(overviewSrc).not.toMatch(/findings in total/)
  })

  it('counts a criterion once when two engines spelled it differently in the same scan', () => {
    const by = Object.fromEntries(findingsByCriterion(UTSW_FILES).map((c) => [c.sc, c.count]))
    expect(by['1.3.1']).toBe(4)   // SC_1_3_1 ×3 + '1.3.1 Info and Relationships' ×1
    expect(by['2.4.4']).toBe(4)   // SC_2_4_4 ×2 + '2.4.4 Link Purpose (In Context)' ×2
    expect(by['1.4.3']).toBe(2)   // SC_1_4_3 ×1 + '1.4.3 Contrast (Minimum)' ×1
    // One entry per criterion in the cloud, so "most common failure" is not decided by spelling.
    const cloud = findingsByCriterion(UTSW_FILES).map((c) => c.sc)
    expect(new Set(cloud).size).toBe(cloud.length)
  })

  // THE DIMENSION CARDS ARE GONE. "Average score by department", "by owner seniority" and the
  // rest were removed from Overview on 2026-09-02 (PRD "ACP Discover and Overview
  // Simplification"). They are pinned as removed rather than deleted from this file, because the
  // three defects below are what a restored card would have to avoid all over again: a heading
  // over an empty <Bars>, a bar drawn from SIM-only metadata, and a one-bar "breakdown" that is
  // an estate average wearing a breakdown's title.
  it('renders no dimension card at all — no heading, and so no heading over blank space', () => {
    expect(UTSW_FILES.every((f) => f.seniority == null)).toBe(true)
    expect(overviewSrc).not.toMatch(/Average score by owner seniority/)
    expect(overviewSrc).not.toMatch(/Average score by department/)
    const html = screen(UTSW_RUN, UTSW_FILES)
    expect(html).not.toMatch(/No owner seniority recorded/)
    expect(html).not.toMatch(/Average score by/)
  })

  it('does not name a department breakdown it no longer draws', () => {
    const unplaceable = UTSW_FILES.map((f) => ({ ...f, department: 'Unassigned' }))
    expect(screen(UTSW_RUN, unplaceable)).not.toMatch(/Every document is .Unassigned./)
    expect(screen(UTSW_RUN, unplaceable)).not.toMatch(/by department/i)
  })
})

// The Overview is where two scans get compared, so the headline count must carry its boundary.
// On 2026-07-30 a folder scan of "UTSW DEMO V2" (4 listed, 4 kept) was read against a whole-Drive
// scan of the same account (8 raw, 3 kept) and the pair was reported as one screen disagreeing
// with itself. Both counts were right. This is the sentence Discover has carried since
// scanScope.js and the Overview did not.
describe('the Overview headline says what its count counts', () => {
  it('names the folder, and says the rest of the Drive was not scanned', () => {
    const html = screen(UTSW_RUN, UTSW_FILES)
    expect(html).toMatch(/4 documents in the Drive folder “UTSW DEMO V2”/)
    expect(html).toMatch(/Documents elsewhere in your Drive were not scanned/)
  })

  it('labels a whole-Drive scan too, so the narrow one is spottable by contrast', () => {
    // A label that appears only on narrow scans is invisible exactly when a reader is comparing.
    expect(screen()).toMatch(/3 documents across your whole Google Drive/)
  })

  it('says nothing at all when the scope was never recorded', () => {
    // "No scope recorded" is not evidence of a whole-Drive scan (scanScope.js).
    const html = screen({ ...UTSW_RUN, scope: null }, UTSW_FILES)
    expect(html).not.toMatch(/whole Google Drive|Drive folder/)
  })
})

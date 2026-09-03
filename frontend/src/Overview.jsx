import { useEffect, useMemo, useRef, useState } from 'react'
import { severityItems } from './charts.jsx'
import SegmentDrawer from './SegmentDrawer.jsx'
import FileDrawer, { statusOf } from './FileDrawer.jsx'
import EstateOnlyDrawer from './EstateOnlyDrawer.jsx'
import { loadDiscoveryInventory, inventoryOnlyRows } from './discoveryInventory.js'
import { findingsByCriterion, findingsByLevel, levelOfFinding } from './wcagFinding.js'
import { analysedCount, avgScore } from './docStatus.js'
import { IDENTITY, SIM, remediableCount, recommendationSummary } from './sim.js'
import { openReport, getScanInventory } from './api.js'
import { loadPublished } from './ontology.js'
import EstateProgressPanel from './EstateProgressPanel.jsx'
import { reconcileBuckets, assessmentEligible } from './estateFunnel.js'
import { reconciliationInputs } from './reconciliationInputs.js'
import { assessMetrics, coverageSentence, SEVERITIES, SEVERITY_LABEL } from './assessMetrics.js'
import AssertionScope from './AssertionScope.jsx'
import NextStep from './NextStep.jsx'
import { CORE_SCS } from './activeScope.js'
import AccordionSection from './AccordionSection.jsx'

// Inline until PR #643 (process-health-pr1) merges — then replace with:
// import ProcessHealthAlert from './ProcessHealthAlert.jsx'
function ProcessHealthAlert({ level, label, children }) {
  const styles = {
    critical: { border: '#B42318', bg: '#FEF3F2', fg: '#7A271A', icon: '✕' },
    warning:  { border: 'var(--warn-fg)', bg: '#FFF7E6', fg: '#6B3A00', icon: '⚠' },
    info:     { border: '#175CD3', bg: '#EFF8FF', fg: '#0B3A7A', icon: 'ℹ' },
    recovered:{ border: '#067647', bg: '#ECFDF3', fg: '#074D31', icon: '✓' },
  }
  const s = styles[level] || styles.info
  return (
    <div role="alert" style={{ display: 'flex', alignItems: 'flex-start', gap: 10,
      padding: '10px 14px', borderRadius: 6, border: `1px solid ${s.border}`,
      borderLeft: `4px solid ${s.border}`, background: s.bg, color: s.fg,
      marginBottom: 12, fontSize: 13 }}>
      <span aria-hidden="true" style={{ fontWeight: 700, flexShrink: 0 }}>{s.icon}</span>
      <span><strong style={{ fontWeight: 700 }}>{label}</strong>{children && <> — {children}</>}</span>
    </div>
  )
}

// The estate dashboard — doubles as the exportable compliance report.
export default function Overview({ run, files, trend, trendDates, onGo, scanList = [], onPickScan, me,
                                   onScan, busy = false, hasDriveToken = false, hasSPToken = false,
                                   onFileTypeChange, cap, assessment }) {
  // Real signed-in org (email domain) — the hardcoded demo org only ever shows in SIM.
  const orgName = SIM ? IDENTITY.org : (me?.email?.split('@')[1]?.replace(/\.[^.]+$/, '') || me?.name || 'your organisation')
  const [seg, setSeg] = useState(null)
  const [selFile, setSelFile] = useState(null)
  const [estOnlyFile, setEstOnlyFile] = useState(null)
  // The per-file estate inventory — every image/video/unsupported file discovery listed but never
  // opened, behind the same paginated `GET /scans/{id}/inventory` route Discover.jsx already reads
  // for lifecycle columns (discoveryInventory.js). Only fetched here to widen "by type"/"by pages"
  // and their drill-downs from the scanned subset to the true estate; every other panel on this
  // screen is unaffected and keeps reading `files` directly.
  const [inv, setInv] = useState(null)
  useEffect(() => {
    let live = true
    setInv(null)      // a new scan invalidates the previous read the instant the id changes
    if (!run?.id) return undefined
    loadDiscoveryInventory(run.id, getScanInventory).then((r) => { if (live) setInv(r) })
    return () => { live = false }
  }, [run?.id])
  // `files` plus the estate-only rows the inventory adds — read by `byType`/`byPages` and their
  // onPick filters ONLY. Every other computation on this screen (scores, findings, departments)
  // stays on `files`, which is correct for them: a never-opened file has no score or finding.
  const estateFiles = useMemo(() => [...files, ...inventoryOnlyRows(files, inv)], [files, inv])
  const reportRef = useRef(null)
  const [exporting, setExporting] = useState(false)
  const [scanExporting, setScanExporting] = useState(false)
  const doScanExport = async () => {
    setScanExporting(true)
    try {
      const { generateScanReport } = await import('./scanReport.js')
      await generateScanReport({ scanId: run.id, files, org: orgName })
    } catch (e) { console.error('scan report export failed', e) }
    finally { setTimeout(() => setScanExporting(false), 600) }
  }
  const doExport = async () => {
    setExporting(true)
    try {
      const now = new Date()
      const quarter = `Q${Math.floor(now.getMonth() / 3) + 1} ${now.getFullYear()}`
      const date = now.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
      const deptScores = Object.entries(files.reduce((a, f) => { if (f.score != null) (a[f.department] = a[f.department] || []).push(f.score); return a }, {}))
        .map(([label, arr]) => ({ label, value: Math.round(arr.reduce((s, x) => s + x, 0) / arr.length), color: '#4B3460' }))
        .sort((a, b) => b.value - a.value).slice(0, 8)
      const topViolations = (wcCloud || []).slice(0, 6).map((v) => ({ label: v.full || v.text, value: v.value }))
      // remediation-effort engine + risk ranking + WCAG-level + per-criterion status — for the detailed report
      const rec = recommendationSummary(files)
      const sevW = { CRITICAL: 4, SERIOUS: 3, MODERATE: 2, MINOR: 1 }
      const riskOf = (f) => (f.issues || []).reduce((a, i) => a + (sevW[i.severity] || 0), 0) * ((f.tags || []).some((t) => ['public-facing', 'high-traffic'].includes(t)) ? 1.6 : 1) + (100 - (f.score ?? 100)) / 15
      const topRisk = [...files].filter((f) => (f.issues || []).length).sort((a, b) => riskOf(b) - riskOf(a)).slice(0, 10)
        .map((f) => ({ file: f.file, dept: f.department, owner: f.owner, score: f.score == null ? 'n/a' : f.score, findings: (f.issues || []).length, action: f.rec?.action || '—', eta: f.rec?.etaMin ? `${(f.rec.etaMin / 60).toFixed(1)}h` : '—' }))
      const publicCritical = files.filter((f) => (f.tags || []).some((t) => ['public-facing', 'high-traffic'].includes(t)) && (f.issues || []).some((i) => i.severity === 'CRITICAL')).length
      // A verdict needs a measurement. With nothing analysed there is no evidence for
      // "ACTION REQUIRED" either — say so rather than let null fall through the comparisons.
      const verdict = auditReady == null ? ['NOT YET ASSESSED', '#5F5E5A']
        : auditReady >= 80 ? ['ON TRACK TO COMPLIANT', 'var(--success-fg)'] : auditReady >= 45 ? ['DEVELOPING', 'var(--warn-fg)'] : ['ACTION REQUIRED', 'var(--info-fg)']
      const criteria = wm.map((c) => ({ sc: c.sc, label: c.name, count: c.count }))
      const { exportGovernanceReport } = await import('./pdfReport.js')
      await exportGovernanceReport({
        org: orgName, quarter, date, scope: 'full document estate',
        total: n, score: run.avg_score, certifiable: run.certifiable, needFix, auditReady,
        uncertain: run.uncertain, error: run.error,
        summary: `Estate accessibility score ${run.avg_score ?? '—'}/100, with ${auditReadyLabel} of documents audit-ready${analysed < n ? ` (${analysed.toLocaleString()} of ${n.toLocaleString()} documents analysed)` : ''}. ${needFix} documents are in the remediation backlog and ${n.toLocaleString()} are under continuous monitoring across ${(trend && trend.length) || 4} scans.`,
        severity, deptScores, topViolations, byLevel, rec, topRisk, criteria,
        legal: { publicCritical, total: n }, lift: { before, after }, verdict,
        ontology: { ver: ontVer, classified: ontDocs.length, crit: ontCrit, high: ontHigh },
      })
    } catch (e) { console.error('PDF export failed', e) }
    finally { setTimeout(() => setExporting(false), 600) }
  }

  // Raw findings grid for analysts — every issue flattened to a row.
  const exportCsv = () => {
    const esc = (v) => `"${String(v == null ? '' : v).replace(/"/g, '""')}"`
    const head = ['Document', 'Department', 'Owner', 'Type', 'Score', 'WCAG', 'Level', 'Severity', 'Detail', 'Auto-fixable', 'Recommended action', 'Effort (min)']
    const rows = []
    files.forEach((f) => (f.issues || []).forEach((i) => rows.push([f.file, f.department, f.owner, (f.type || '').toUpperCase(), f.score ?? '', (i.wcag || '').replace(/^SC_/, '').replace(/_/g, '.'), i.level, i.severity, i.detail, i.auto ? 'yes' : 'no', f.rec?.action || '', f.rec?.etaMin || ''])))
    const csv = [head, ...rows].map((r) => r.map(esc).join(',')).join('\r\n')
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
    const u = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = u; a.download = 'mova-findings-export.csv'; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(u), 1000)
  }

  // Filter by `label` (the statusOf value), title with `display` (the human one) — the drill-in
  // must key on the machine value or it opens an empty drawer.
  const pickStatus = (s) => { const fs = files.filter((f) => statusOf(f) === s.label); setSeg({ title: `${s.display || s.label} documents`, subtitle: `${fs.length} of ${files.length}`, files: fs }) }
  const pickSeverity = (it) => { const sev = it.label.toUpperCase(); const fs = files.filter((f) => (f.issues || []).some((i) => i.severity === sev)); setSeg({ title: `${it.label} findings`, subtitle: `${fs.length} document(s) affected`, files: fs }) }

  const n = run.files || 0
  const needFix = remediableCount(files) // docs with a remediation action — matches the Remediate tab exactly
  // Published business ontology — surfaced for leadership so the org-aware prioritisation is visible here too.
  const ontDocs = files.filter((f) => f.ont)
  const ontCrit = ontDocs.filter((f) => f.ont.priority === 'Critical').length
  const ontHigh = ontDocs.filter((f) => f.ont.priority === 'High').length
  const ontVer = loadPublished()?.version
  // Verify + Publish are REAL counts, never projections: a document is "verified" when it is
  // confirmed compliant (run.certifiable — passed as-is, or remediated then re-scan-cleared),
  // and "published" only when it has an actual published record (file_records.published_at).
  const publish = files.filter((f) => f.published_at).length
  // How much of the estate was actually opened. A Discover-only scan (ADR 0020) lists the
  // inventory without analysing it, and a cancelled/interrupted one stops partway, so `n` is
  // the documents we KNOW ABOUT while `analysed` is the documents we know ANYTHING about.
  const analysed = analysedCount(files)
  // The Overview grows organically across the funnel: the discovery section fills in once an estate
  // has been inventoried, and the assessment section reveals only once documents have actually been
  // assessed (analysed > 0). A discovered-but-not-yet-assessed estate shows the discovery numbers
  // and a prompt to run Assess — never a page of empty findings charts, which is the failure the
  // old "Overview stays blank until assessed" gate (OV-01/OV-04) was avoiding. Reveal-as-completed
  // solves that concern without hiding the discovery work the estate has already done.
  const stageAssessed = analysed > 0
  // Estate-coverage funnel progress (stages 4-9). Discovery denominators (1-3) come from
  // run.scope.inventory; these come from the file rows — each a REAL count, never a projection.
  //   human_review = documents carrying at least one REVIEW-lane finding (ADR 0023: assessed-for-
  //     review, a person must clear them before they can certify) — the estate's human-review load.
  //   published    = documents with an actual published record (file_records.published_at), already
  //     computed above as `publish` and used by the horizontal funnel — it was the one number left
  //     reading "pending" while sitting one variable away.
  // audit-ready is a rate, and a rate needs a denominator that was measured. Over an estate
  // nobody analysed it is not 0% — it is unknown, and printing "0%" asserts that every one of
  // 258 documents was checked and none passed. Both this and the certifiable tile render '—'
  // rather than a number derived from an absent one.
  const auditReady = (analysed && n && run.certifiable != null) ? Math.round((run.certifiable / n) * 100) : null
  const auditReadyLabel = auditReady == null ? '—' : `${auditReady}%`

  // ── The four headline tiles (board 7) ───────────────────────────────────────────────────────
  // Read, never derived. `rec` is the SAME call AssessmentReconciliation makes below, so the two
  // are one computation and the tiles cannot disagree with the partition that explains them.
  // `metrics` is the module the Assess tab's summary uses, so one run cannot report two different
  // findings totals depending on which tab you are standing on.
  const rec = reconcileBuckets(run?.scope?.inventory, reconciliationInputs(run, files))
  const metrics = assessMetrics(files, { cap, assessment })
  // The by-severity addends for the assessment section's equation — printed so the partition is
  // checkable on screen, the same rule the Assess tab's summary obeys.
  const sevAddends = metrics
    ? [...SEVERITIES.map((s) => metrics.bySeverity[s]),
       ...(metrics.bySeverity.UNKNOWN > 0 ? [metrics.bySeverity.UNKNOWN] : [])]
    : []
  // An em dash, never a zero. "0 findings" over an estate nobody assessed is the same false
  // verdict as a completed run that found nothing - the distinction this product exists to make.
  const tile = (v) => (v == null ? '\u2014' : v.toLocaleString())
  // Undecided lifecycle recommendations, for the NEXT panel's backlog line. NULL when the bucket
  // was never measured — "0 awaiting" from an unread column would quietly close a loop nobody
  // actually closed.
  const lifecycleBucket = rec ? rec.rows.find((r) => r.key === 'lifecycle') : null
  const lifecycleAwaiting = lifecycleBucket && lifecycleBucket.measured ? lifecycleBucket.value : null

  // assessment-eligible count for the funnel — from the scan's own inventory summary, so
  // it tracks the real discovery-side filter, not a derivation from file rows (which only
  // covers the opened subset).
  const eligible = assessmentEligible(run?.scope?.inventory)
  const severity = severityItems(files)
  // "Findings by severity" buckets CRITICAL/SERIOUS/MODERATE/MINOR — the blocking severities.
  // An advisory finding (severity REVIEW, ADR 0023: assessed-for-review, never certified) has
  // none of those, so it is in no bucket and the panel's total silently excludes it. On
  // 2026-07-30 that panel read 6 while the estate held 9 recorded findings and the WCAG-level
  // panel beside it counted all 9. Both totals are right; neither said what it was counting.
  //
  // The panel is NOT widened to swallow them — severityItems also feeds RiskScore, whose
  // critical/serious weighting is a leadership risk view of blocking work, and an advisory is
  // not blocking work. So the screen says which question each panel answers instead.
  const advisoryFindings = files.reduce((a, f) => a + (f.issues || []).filter((i) => String(i.severity || '').toUpperCase() === 'REVIEW').length, 0)
  const allFindings = files.reduce((a, f) => a + (f.issues || []).length, 0)

  // inventory distributions
  const countBy = (fn, pop = files) => Object.entries(pop.reduce((m, f) => { const k = fn(f); if (k != null) m[k] = (m[k] || 0) + 1; return m }, {})).sort((a, b) => b[1] - a[1])
  const PLUM = '#7a5c8e'
  const NA_GREY = '#9a948f'   // "not measured" — never a score band, so it reads as absent, not bad
  const bySource = countBy((f) => f.sourceName).map(([label, value]) => ({ label, value, color: PLUM }))
  // Over estateFiles, not files: an estate that is mostly images/video must not render this panel
  // as if it were document-only (see discoveryInventory.js's inventoryOnlyRows for the gap this
  // closes — the identical failure DiscoveryResults.jsx's own "By file type" panel had).
  const byType = countBy((f) => (f.type || '').toUpperCase(), estateFiles).map(([label, value]) => ({ label, value, color: PLUM }))
  // Total pages per type, for the treemap's "by total pages" toggle — sums only files that
  // actually carry a page count (a discover-only file's `pages` is null, not zero). `byPages` is
  // null, not a zero-filled array, when NOTHING in the estate has been paginated yet: the toggle
  // that switches to it is not even offered in that case (see EstateTreemap), rather than
  // switching to a chart of all-zero bars.
  const pageSums = {}
  let anyPages = false
  for (const f of estateFiles) {
    if (f.pages == null) continue
    anyPages = true
    const k = (f.type || '').toUpperCase()
    pageSums[k] = (pageSums[k] || 0) + f.pages
  }
  const byPages = anyPages ? Object.entries(pageSums).map(([label, value]) => ({ label, value })) : null
  const byDept = countBy((f) => f.department).map(([label, value]) => ({ label, value, color: PLUM }))
  // Collapsed across the three spellings a finding's `wcag` arrives in — see wcagFinding.js.
  // Keying the raw string listed 1.3.1 twice, as "info & relationships" and "Info and
  // Relationships", and split its findings across the two.
  const wm = findingsByCriterion(files)
  const wcCloud = wm.map((c) => ({ text: c.name, value: c.count, full: c.label }))

  // --- analysis by dimension (score / severity / WCAG level) — not just counts ---
  // UNSCORED IS NOT ZERO. `avgScore` (docStatus.js) returns null for a group nobody analysed,
  // and null travels all the way to the bar: NA_GREY, no fill, '—' in place of the number.
  // Overview's own copy of the average used to return 0, which rendered "Finance 0" for a
  // cancelled scan of unopened inventory rows — a failing grade for work never done.
  const scoreColor = (s) => s == null ? NA_GREY : s >= 90 ? '#639922' : s >= 50 ? '#BF8C00' : '#2E72C9'
  const groupBy = (fn) => files.reduce((m, f) => { const k = fn(f); if (k != null) (m[k] = m[k] || []).push(f); return m }, {})
  const scoreItem = ([label, fs]) => { const v = avgScore(fs); return { label, value: v, color: scoreColor(v) } }
  // Unscored groups sort last — they are not the lowest score, they are absent from the ranking.
  const byScoreAsc = (a, b) => (a.value == null) - (b.value == null) || a.value - b.value
  const scoreByDept = Object.entries(groupBy((f) => f.department)).map(scoreItem).sort(byScoreAsc)
  const SR_ORDER = ['Executive', 'Director', 'Manager', 'Staff']
  const senGroups = groupBy((f) => f.seniority)
  const scoreBySeniority = SR_ORDER.filter((s) => senGroups[s]).map((s) => scoreItem([s, senGroups[s]]))
  // `seniority` is SIM-only: a real scan's file records carry no owner, and ontology.annotate
  // gap-fills type/department/tags but never this. So on EVERY real scan the list is empty and
  // <Bars items={[]}/> renders nothing at all — the card came out as a heading over blank space,
  // reported from the live demo build on 2026-07-30 beside three panels that did have numbers.
  // A blank card is the worst of the three options: an empty state says "nothing to show and
  // here is why", a hidden card says nothing, and a blank one looks like a number that failed
  // to load. It is also how the estate-wide contradiction announced itself the first time —
  // the blank `certifiable` tile in #77.
  const noSeniorityData = !scoreBySeniority.length
  // Same shape, one step milder: a real scan has no department either, so classifyByName's
  // keyword heuristic files everything it cannot place under "Unassigned". One bar labelled
  // "Unassigned" is not a departmental breakdown, and must not be read as one.
  const deptAllUnassigned = scoreByDept.length === 1 && scoreByDept[0].label === 'Unassigned'
  // Only the groups with a real measurement can carry a claim about scores.
  const deptRanked = scoreByDept.filter((d) => d.value != null)
  // Real scan findings carry no `level` — only SIM's corpus does — so reading `i.level` counted
  // zero on every real scan and this panel rendered "No open findings." beside a severity panel
  // reporting six. The level comes from the WCAG catalog (wcagFinding.js), and a criterion the
  // catalog cannot place is shown as its own row rather than defaulted into Level A.
  const levelC = findingsByLevel(files)
  const byLevel = [['A', 'var(--info-fg)', 'Level A · must-have'], ['AA', '#D85A30', 'Level AA · legal target'],
                   ['AAA', '#9a948f', 'Level AAA · optional'], ['unknown', '#9a948f', 'level not in the catalog']]
    .filter(([k]) => levelC[k]).map(([k, color, label]) => ({ label, value: levelC[k], color, lvl: k }))
  const band = (lo, hi) => files.filter((f) => f.score != null && f.score >= lo && f.score <= hi).length
  const scoreBands = [
    { label: '90–100 · certifiable', value: band(90, 100), color: '#639922' },
    { label: '50–89 · needs work', value: band(50, 89), color: '#BF8C00' },
    { label: 'below 50 · at risk', value: band(0, 49), color: '#2E72C9' },
    { label: 'n/a · unreadable', value: files.filter((f) => f.score == null).length, color: NA_GREY },
  ].filter((d) => d.value)

  // On-demand insights — computed strictly from this scan's data, with correct units
  // (findings ≠ documents) and NO fabricated benchmarks or assumed causes. If it isn't
  // derivable from the numbers below, it doesn't go in the sentence.
  const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0)
  const sevTotal = severity.reduce((a, s) => a + s.value, 0)
  const sevHigh = severity.filter((s) => s.label === 'critical' || s.label === 'serious').reduce((a, s) => a + s.value, 0)
  // Count the documents that actually have findings. The old `n - certifiable - uncertain -
  // error` was the same subtraction that broke statusSegments: it swept clean and unanalysed
  // documents into "open findings", and returned the whole estate when the run counters were
  // NULL. `statusOf` is the same verdict the donut and its drill-in now use.
  const issuesOnly = files.filter((f) => statusOf(f) === 'issues').length
  const INS = {
    status: `${auditReady == null ? 'No document in this scan has been analysed yet, so no share is certifiable' : `${auditReady}% of documents are certifiable`}${issuesOnly ? `; ${issuesOnly} ${issuesOnly === 1 ? 'has' : 'have'} open findings, most of them auto-fixable — a first pass lifts this quickly` : ''}.`,
    severity: sevTotal ? `Critical & serious findings (${sevHigh}) are ${pct(sevHigh, sevTotal)}% of the ${sevTotal} blocking finding${sevTotal !== 1 ? 's' : ''}${wcCloud[0] ? `, mostly ${wcCloud[0].text}` : ''}. Clear these first to cut the most legal risk.` : (advisoryFindings ? `No blocking findings — but ${advisoryFindings} advisory finding${advisoryFindings === 1 ? '' : 's'} ${advisoryFindings === 1 ? 'is' : 'are'} waiting on a human to look at ${advisoryFindings === 1 ? 'it' : 'them'}.` : 'No open findings.'),
    source: bySource[0] ? `${bySource[0].label} holds the most documents (${bySource[0].value} of ${n}).` : '',
    type: byType[0] ? `${byType[0].label} is your largest format (${byType[0].value} of ${n} document${n !== 1 ? 's' : ''}).${/pdf/i.test(byType[0].label) ? ' PDFs are typically the hardest to remediate — tagging and reading order.' : ''}` : '',
    dept: byDept[0] ? `${byDept[0].label} has the most documents (${byDept[0].value} of ${n}).` : '',
    wcag: wcCloud[0] ? `WCAG ${wcCloud[0].full} is the most common failure (${wcCloud[0].value} finding${wcCloud[0].value !== 1 ? 's' : ''} across ${n} document${n !== 1 ? 's' : ''}). It's largely automatable — one class of fix clears a big share of your findings.` : '',
    // A ranking needs at least one measured group; with none, say that instead of naming a
    // "lowest" department on the strength of a score nobody computed.
    scoreByDept: !deptRanked.length
      ? (scoreByDept.length ? 'No document in these departments has been analysed yet, so there is no average score to compare.' : '')
      : deptRanked.length === 1
        ? `${deptRanked[0].label} is the only department with an analysed document (${deptRanked[0].value}/100); the rest have nothing scored to compare against yet.`
        : `${deptRanked[0].label} has the lowest average score (${deptRanked[0].value}/100) — the highest-leverage starting point. ${deptRanked.at(-1).label} leads at ${deptRanked.at(-1).value}/100; their approach is worth studying.`,
    scoreBySeniority: (() => {
      if (!scoreBySeniority.length) return ''
      const exec = scoreBySeniority.find((s) => s.label === 'Executive')
      if (!exec) return 'No Executive-owned documents in this scan.'
      return exec.value == null
        ? 'No Executive-owned document has been analysed yet, so there is no score for leadership content. These drive legal exposure — worth putting on the fast track.'
        : `Executive-owned documents score ${exec.value}/100. Leadership content drives legal exposure and sets the tone — keep these on the fast track.`
    })(),
    // Name the level each number belongs to. `byLevel[0]` is only Level A when Level A has
    // findings, so reading the headline count off it captioned an AA total "Level A findings".
    wcagLevel: byLevel.length ? `${levelC.A || 0} Level A findings are the legal floor and most automatable — address these first. Level AA (${levelC.AA || 0} findings) is the ADA/EAA/508 statutory target; Level AAA is optional.` : 'No findings by WCAG level.',
    scoreBand: `${band(90, 100)} documents are certifiable now (${pct(band(90, 100), n)}% of the estate). The ${band(50, 89)} in the 50–89 band are within striking distance — remediation here produces the fastest estate-level lift.`,
  }

  const scoredNow = files.filter((f) => f.score != null)
  // Real measured baseline — average of the scored documents in this run (or the run's
  // stored avg). No magic fallback: if nothing is scored yet, `before` is null and the
  // projected-lift panel below is hidden rather than showing an invented number.
  const before = run.avg_score ?? (scoredNow.length ? Math.round(scoredNow.reduce((a, f) => a + f.score, 0) / scoredNow.length) : null)
  const after = (() => {
    if (before == null) return null
    const SEV_PEN = { CRITICAL: 16, SERIOUS: 11, MODERATE: 5, MINOR: 2 }
    const scored = files.filter((f) => f.score != null)
    if (!scored.length) return Math.min(100, before + 12)
    const projScores = scored.map((f) => {
      if (f.rec?.action !== 'auto') return f.score
      const gain = (f.issues || []).filter((i) => i.auto).reduce((s, i) => s + (SEV_PEN[i.severity] || 0), 0)
      return Math.min(100, f.score + gain)
    })
    return Math.min(100, Math.round(projScores.reduce((a, b) => a + b, 0) / projScores.length))
  })()
  const scopePanel = <AssertionScope
    run={run}
    fileCount={files.length > 0
      ? files.length
      : (run?.scope?.inventory?.assessment_eligible ?? 0)}
    coreScs={CORE_SCS}
    rec={rec}
  />
  const hasEstateProgress = run?.scope?.inventory?.discovered != null || files.length > 0
  return (
    <>
      <div className="dashtoolbar">
        <details className="reports-menu">
          <summary className="exportbtn">Reports</summary>
          <div className="reports-menu-items" aria-label="Report exports">
            <button type="button" onClick={doExport} disabled={exporting}>{exporting ? 'Generating PDF…' : 'Quarterly governance report'}</button>
            <button type="button" onClick={doScanExport} disabled={scanExporting} title="Whole-scan estate report: conformance, WCAG failure heatmap, per-department breakdown, remediation throughput, HITL queue & a per-document appendix">{scanExporting ? 'Generating PDF…' : 'Scan report'}</button>
            <button type="button" onClick={exportCsv} title="Every finding as a spreadsheet row">Findings (CSV)</button>
            {!SIM && run?.id && (
              <button type="button" onClick={() => openReport(run.id)} title="Backend-generated WCAG compliance report PDF">Compliance report (PDF)</button>
            )}
          </div>
        </details>
      </div>
      {!hasEstateProgress && scopePanel}
      <div ref={reportRef}>
      {/* Process health banners — rendered above the findings summary so a degraded run is
          immediately visible. Amber when files errored out (could not be opened); red when the
          worker job itself failed. Both conditions mean findings may be incomplete. */}
      {run.status === 'failed' && (
        <ProcessHealthAlert level="critical" label="Assessment process encountered worker errors">
          results may be incomplete
        </ProcessHealthAlert>
      )}
      {(run.error > 0) && (
        <ProcessHealthAlert level="warning" label={`${run.error} document${run.error === 1 ? '' : 's'} could not be opened`}>
          findings may be incomplete
        </ProcessHealthAlert>
      )}
      {/* 0-FILE EMPTY STATE — a scan that completed but found nothing in its source. The metric
          tiles show em-dashes and the reconciliation renders nothing, so without this prompt the
          screen offers only "Run assessment →" beside a "0 documents discovered" count, which has
          nothing to assess. Direct the user to their source configuration instead. */}
      {n === 0 && run.status !== 'running' && run.status !== 'failed' && (
        <section className="panel" style={{ textAlign: 'center', padding: '24px 20px', marginBottom: 16 }}>
          <p style={{ fontSize: 15, fontWeight: 600, margin: '0 0 6px' }}>No documents found in this scan</p>
          <p className="muted" style={{ margin: '0 0 14px', fontSize: 13 }}>
            The scan completed but discovered no files. Check that your source folder is configured
            and contains documents in a supported format (PDF, Word, PowerPoint, Excel, HTML),
            then return to the Discover tab to re-scan.
          </p>
          <button onClick={() => onGo && onGo('discover')}>Go to Discover →</button>
        </section>
      )}
      {/* ── ESTATE PROGRESS — funnel, doc-types, and pending work. Rendered from the same inventory
             the reconciliation panel above uses so the numbers stay consistent. Grows in when there
             is any estate data (discovered or files). Hidden behind null-return inside the component
             when neither inventory nor files exist yet. */}
      <EstateProgressPanel
        inventory={run.scope?.inventory}
        analysed={analysed}
        needFix={needFix}
        certifiable={run.certifiable}
        published={publish}
        errorCount={run.error}
        files={files}
        estateFiles={estateFiles}
        onGo={onGo}
        collapsible
        afterProgress={hasEstateProgress ? scopePanel : null}
      />

      {/* ── ASSESSMENT — the section that grows in once documents have actually been assessed.
             Below discovery, above the detailed findings charts. Before a run it is a prompt, not an
             empty grid; after one it is the seven metrics (board 4), read from the SAME assessMetrics
             the Assess tab reports so one run never shows two different totals across two tabs. ── */}
      {stageAssessed && metrics ? (
        <>
          {/* Supporting assessment evidence stays collapsed. Its concise coverage summary remains
              visible in the header; the four estate stages above own the open headline view. */}
          <AccordionSection id="assessment-summary" className="panel overview-assessment"
                            ariaLabel="Assessment summary" defaultOpen={false}
                            title="Assessment" meta={coverageSentence(metrics)}>
              <>
                <div className="metrics">
                  <div className="metric" title="Documents where at least one selected check completed.">
                    <span>documents assessed</span><b>{metrics.documentsAssessed}</b></div>
                  <div className="metric" title="Assessed documents carrying at least one unresolved finding.">
                    <span>needing attention</span><b style={{ color: 'var(--warn-fg)' }}>{metrics.documentsNeedingAttention}</b></div>
                  <div className="metric" title="Unresolved finding instances across all assessed documents. One criterion can produce many.">
                    <span>total findings</span><b>{metrics.totalFindings}</b></div>
                  <div className="metric" title="Findings with a deterministic remediation — same input, same fix, no person needed.">
                    <span>auto-fix available</span><b style={{ color: '#2F7D32' }}>{metrics.autoFixAvailable}</b></div>
                  <div className="metric" title="Findings needing a person's judgement, including every AI-drafted fix awaiting approval.">
                    <span>human review required</span><b>{metrics.humanReviewRequired}</b></div>
                  <div className="metric" title="Selected checks that could not run — no method for these formats. Not passes and not failures.">
                    <span>unable to assess</span><b>{metrics.unableToAssess} <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>checks</span></b></div>
                </div>
                {/* The severity partition, added up on screen — the 7th metric, printed as an equation so
                    a reader can check it against Total findings rather than take it on trust. */}
                {metrics.totalFindings > 0 && (
                  <div className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>
                    By severity: {SEVERITIES.map((s, i) => (
                      <span key={s}>{i > 0 ? ' · ' : ''}<b>{metrics.bySeverity[s]}</b> {SEVERITY_LABEL[s]}</span>
                    ))} — {sevAddends.join(' + ')} = {metrics.totalFindings}
                  </div>
                )}
              </>
          </AccordionSection>

          {/* SO WHAT NOW (board 7). The only panel on this screen with a primary action. */}
          <NextStep metrics={metrics}
                    awaiting={lifecycleAwaiting}
                    onRemediate={() => onGo && onGo('remediate')}
                    onReviewLifecycle={() => onGo && onGo('discover')} />
        </>
      ) : (
        <AccordionSection id="assessment-summary" className="panel overview-runassess"
                          ariaLabel="Assessment not yet run" defaultOpen
                          title="Assessment" meta="not yet run">
          {(n > 0 ? (
            <>
              <p className="muted" style={{ margin: '4px 0 12px' }}>
                {n.toLocaleString()} document{n === 1 ? '' : 's'} discovered
                {eligible != null && eligible < n && ` · ${eligible.toLocaleString()} eligible for WCAG assessment`}.{' '}
                Run an assessment to score them against WCAG 2.1 — findings, coverage and the
                severity breakdown appear here once it finishes.
              </p>
              <button onClick={() => onGo && onGo('assess')}>Run assessment →</button>
            </>
          ) : (
            <p className="muted" style={{ margin: '4px 0 0' }}>
              No documents have been discovered yet. Configure a source and run a scan from
              the Discover tab first.
            </p>
          ))}
        </AccordionSection>
      )}

      </div>

      {/* An estate-only row (image/video/unsupported — never opened, see inventoryOnlyRows) has no
          assessment record for FileDrawer to show; route it to the lighter EstateOnlyDrawer
          instead of opening FileDrawer on a file it was never built to describe. */}
      {seg &&<SegmentDrawer title={seg.title} subtitle={seg.subtitle} files={seg.files} onClose={() => setSeg(null)} onPickFile={(f) => (f._estateOnly ? setEstOnlyFile(f) : setSelFile(f))} />}
      {estOnlyFile && <EstateOnlyDrawer file={estOnlyFile} onClose={() => setEstOnlyFile(null)} />}
      {selFile && <FileDrawer file={selFile} scanId={run.id} onClose={() => setSelFile(null)} />}
    </>
  )
}

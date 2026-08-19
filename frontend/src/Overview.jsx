import { useEffect, useRef, useState } from 'react'
import ScanSetup from './ScanSetup.jsx'
import { Sparkline } from './ScoreRing.jsx'
import { Donut, Bars, statusSegments, severityItems } from './charts.jsx'
import SegmentDrawer from './SegmentDrawer.jsx'
import FileDrawer, { statusOf } from './FileDrawer.jsx'
import { findingsByCriterion, findingsByLevel, levelOfFinding } from './wcagFinding.js'
import { analysedCount, avgScore } from './docStatus.js'
import { remediationEligibleCount } from './assessCoverage.js'
import { IDENTITY, SIM, remediableCount, recommendationSummary } from './sim.js'
import { openReport } from './api.js'
import { loadPublished } from './ontology.js'
import WordCloud from './WordCloud.jsx'
import Insight from './Insight.jsx'
import { TraceChip } from './Transparency.jsx'
import PiiPanel from './PiiPanel.jsx'
import { scopeChip, scopeSentence, isNarrowScope } from './scanScope.js'
import ScanScopeChip from './ScanScopeChip.jsx'
import EstateCoverage from './EstateCoverage.jsx'

// The estate dashboard — doubles as the exportable compliance report.
export default function Overview({ run, files, trend, trendDates, onGo, scanList = [], onPickScan, me,
                                   onScan, busy = false, hasDriveToken = false, hasSPToken = false,
                                   onFileTypeChange }) {
  // Real signed-in org (email domain) — the hardcoded demo org only ever shows in SIM.
  const orgName = SIM ? IDENTITY.org : (me?.email?.split('@')[1]?.replace(/\.[^.]+$/, '') || me?.name || 'your organisation')
  const [on, setOn] = useState(false)
  const [seg, setSeg] = useState(null)
  const [selFile, setSelFile] = useState(null)
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
  useEffect(() => { const t = setTimeout(() => setOn(true), 80); return () => clearTimeout(t) }, [])
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
        : auditReady >= 80 ? ['ON TRACK TO COMPLIANT', '#3B6D11'] : auditReady >= 45 ? ['DEVELOPING', '#854F0B'] : ['ACTION REQUIRED', '#1F5FA8']
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
  const verify = run.certifiable || 0
  const publish = files.filter((f) => f.published_at).length
  // How much of the estate was actually opened. A Discover-only scan (ADR 0020) lists the
  // inventory without analysing it, and a cancelled/interrupted one stops partway, so `n` is
  // the documents we KNOW ABOUT while `analysed` is the documents we know ANYTHING about.
  const analysed = analysedCount(files)
  // Estate-coverage funnel progress (stages 4-9). Discovery denominators (1-3) come from
  // run.scope.inventory; these come from the file rows — each a REAL count, never a projection.
  //   human_review = documents carrying at least one REVIEW-lane finding (ADR 0023: assessed-for-
  //     review, a person must clear them before they can certify) — the estate's human-review load.
  //   published    = documents with an actual published record (file_records.published_at), already
  //     computed above as `publish` and used by the horizontal funnel — it was the one number left
  //     reading "pending" while sitting one variable away.
  const humanReview = files.filter((f) =>
    (f.issues || []).some((i) => String(i.severity || '').toUpperCase() === 'REVIEW')).length
  const estateProgress = {
    assessed: analysed,
    issues: files.filter((f) => (f.issues || []).length).length,
    // The funnel's "remediation eligible" is the honest finding-level count — documents with at least
    // one AUTO/AI-fixable finding — not `needFix` (documents with any remediation ACTION, which the
    // "need remediation" metric and the Remediate tab use). A document whose every open finding is
    // human-only is assessable but not remediable, and the funnel should say so.
    remediation_eligible: remediationEligibleCount(files),
    remediated: files.filter((f) => f.remediated_at || f.drive_write_url).length,
    human_review: humanReview,
    published: publish,
  }
  // audit-ready is a rate, and a rate needs a denominator that was measured. Over an estate
  // nobody analysed it is not 0% — it is unknown, and printing "0%" asserts that every one of
  // 258 documents was checked and none passed. Both this and the certifiable tile render '—'
  // rather than a number derived from an absent one.
  const auditReady = (analysed && n && run.certifiable != null) ? Math.round((run.certifiable / n) * 100) : null
  const auditReadyLabel = auditReady == null ? '—' : `${auditReady}%`
  const maxN = Math.max(1, n)

  const stages = [
    { label: 'Discover', v: n, go: 'discover' },
    { label: 'Assess', v: n, go: 'assess' },
    { label: 'Remediate', v: needFix, go: 'remediate' },
    { label: 'Verify', v: verify, go: 'remediate' },
    { label: 'Publish', v: publish, go: 'monitor' },
  ]
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
  const countBy = (fn) => Object.entries(files.reduce((m, f) => { const k = fn(f); if (k != null) m[k] = (m[k] || 0) + 1; return m }, {})).sort((a, b) => b[1] - a[1])
  const PLUM = '#7a5c8e'
  const NA_GREY = '#9a948f'   // "not measured" — never a score band, so it reads as absent, not bad
  const bySource = countBy((f) => f.sourceName).map(([label, value]) => ({ label, value, color: PLUM }))
  const byType = countBy((f) => (f.type || '').toUpperCase()).map(([label, value]) => ({ label, value, color: PLUM }))
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
  const byLevel = [['A', '#1F5FA8', 'Level A · must-have'], ['AA', '#D85A30', 'Level AA · legal target'],
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
  return (
    <>
      <div className="dashtoolbar">
        <button className="exportbtn" onClick={doExport} disabled={exporting}>{exporting ? 'Generating PDF…' : '⤓ Quarterly governance report'}</button>
        <button className="exportbtn alt" onClick={doScanExport} disabled={scanExporting} title="Whole-scan estate report: conformance, WCAG failure heatmap, per-department breakdown, remediation throughput, HITL queue & a per-document appendix">{scanExporting ? 'Generating PDF…' : '⤓ Export scan report'}</button>
        <button className="exportbtn alt" onClick={exportCsv} title="Every finding as a spreadsheet row">⤓ Findings (CSV)</button>
        {!SIM && run?.id && (
          <button className="exportbtn alt" onClick={() => openReport(run.id)} title="Backend-generated WCAG compliance report PDF">⤓ Compliance report (PDF)</button>
        )}
      </div>
      {/* The scan scope, EDITABLE, on the first tab — after a scan as well as before one.
          EmptyState renders ScanSetup only while `run` is null, so the criteria and file types
          were reachable exactly once: on a workspace that had never scanned. Every session
          after the first opened on this dashboard with no way back to the decision that shapes
          every number on it, and the only remaining editors were two panels inside Settings.

          Collapsed by default, and the same <details> pattern Discover uses to fold Upload in:
          the primary job of this screen is still to report, so an always-open editor would
          compete with the metrics for the top of the page. <details> is natively
          keyboard-operable, so this adds no focus handling of its own.

          Deliberately OUTSIDE reportRef — that node is what the PDF export rasterises, and a
          collapsed control has no place in an exported compliance record. */}
      {onScan && (
        <details className="panel scopeeditor">
          <summary>Scan scope <span className="muted">· which checks, and which file types</span></summary>
          <ScanSetup onScan={onScan} busy={busy}
                     hasDriveToken={hasDriveToken} hasSPToken={hasSPToken}
                     onFileTypeChange={onFileTypeChange} />
        </details>
      )}
      <div ref={reportRef}>
      <div className="metrics">
        <div className="metric"><span>documents</span><b>{n.toLocaleString()}</b></div>
        <div className="metric"><span>certifiable</span><b style={{ color: '#3B6D11' }}>{run.certifiable ?? '—'}</b></div>
        <div className="metric" title="Documents with an open finding and a remediation action — auto-fix, review, or manual rebuild (matches the Remediate tab). A document with no findings is never counted here."><span>need remediation</span><b style={{ color: '#854F0B' }}>{needFix}</b></div>
        <div className="metric" title={auditReady == null ? 'Not computable yet — no document in this scan has been analysed, so there is no measured share to report' : 'Share of documents that are certifiable today (certifiable ÷ total)'}><span>audit-ready</span><b>{auditReadyLabel}</b></div>
      </div>
      {/* WHAT THE COUNT COUNTS. Discover has said this since scanScope.js; the Overview did not,
          and it is the screen where two scans get compared. On 2026-07-30 a folder scan of "UTSW
          DEMO V2" (4 listed, 4 kept) was read against a whole-Drive scan of the same account
          (8 raw, 3 kept) and the pair was reported as one screen disagreeing with itself. Both
          counts were right; neither said what it was a count OF. The chip in the scan-history
          table below already carries this, but only for a reader who finds the row marked
          "viewing" — the headline number needs it too. */}
      {scopeSentence(run.scope, n) && (
        <p className={isNarrowScope(run.scope) ? 'scopewarn' : 'muted'} style={{ margin: '2px 0 10px', fontSize: 12.5 }}
           role={isNarrowScope(run.scope) ? 'status' : undefined}>
          {isNarrowScope(run.scope) ? '⚠ ' : ''}{scopeSentence(run.scope, n)}
        </p>
      )}
      {/* WHICH CRITERIA this scan covered, from its FROZEN scan_scope (R6 / Phase 3b) — beside the
          file boundary above, which says which FILES. Both are read from the run, not the live
          global scope, so an operator who changed the global scope after this scan still sees what
          THIS scan assessed. Carries the change-scope-&-re-scan affordance and its impact estimate. */}
      <ScanScopeChip run={run} fileCount={n} onScan={onScan} busy={busy} />
      {/* Say it on screen when the tiles above describe a different set of documents than the
          estate total does — a partly-analysed scan is the case that made every panel look
          like it was contradicting the others. */}
      {analysed < n && (
        <p className="muted" style={{ margin: '2px 0 10px' }}>
          Scope: <b>{analysed.toLocaleString()}</b> of {n.toLocaleString()} documents have been analysed
          {run.status === 'cancelled' || run.status === 'interrupted' ? ` — this scan was ${run.status} before it finished` : ' — the rest were discovered but not yet assessed'}.
          Findings, certifiable and audit-ready describe the analysed documents only.
        </p>
      )}

      {/* Whole-estate coverage: the three denominators (discovered / assessment-eligible /
          remediation-eligible) as a funnel + format composition + capability-status split, from the
          scan's real scope.inventory. Only shown once discovery has inventoried the estate. */}
      {run.scope?.inventory?.discovered > 0 && (
        <EstateCoverage report={run} progress={estateProgress} />
      )}

      {ontDocs.length > 0 && (
        <div className="ontovbar">
          <span className="ontovtag">⬆ Business ontology{ontVer ? ` v${ontVer}` : ''} active</span>
          <span className="ontovtext"><b>{ontDocs.length}</b> of {n.toLocaleString()} documents classified by your rules — <b style={{ color: '#1F5FA8' }}>{ontCrit} Critical</b> · <b style={{ color: '#854F0B' }}>{ontHigh} High</b> by business priority</span>
        </div>
      )}

      {scanList.length > 0 && (
        <section className="panel">
          <h2>Scan history <span className="muted" style={{ fontWeight: 400 }}>· master score = latest run · click a row to view it</span></h2>
          <div className="tablewrap"><table>
            <thead><tr><th></th><th>scan</th><th>score</th><th>change</th><th>certifiable</th><th>source</th><th></th></tr></thead>
            <tbody>
              {scanList.map((s, i) => {
                const prev = scanList[i + 1]
                const d = (prev?.avg_score != null && s.avg_score != null) ? s.avg_score - prev.avg_score : null
                const isCurrent = s.id === run.id
                const dt = s.completed_at ? new Date(s.completed_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '—'
                return (
                  <tr key={s.id} className="filerow" role="button" tabIndex={0}
                    onClick={() => onPickScan?.(s.id)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPickScan?.(s.id) } }}
                    style={isCurrent ? { background: '#F4EEFC' } : undefined}>
                    <td>{i === 0 && <span className="badge" style={{ background: '#EDE7FB', color: '#6D28D9' }}>★ master</span>}</td>
                    <td>{dt}{isCurrent && <span className="muted"> · viewing</span>}</td>
                    <td className="scorecell"><b>{s.avg_score ?? 'n/a'}</b><span className="muted">/100</span></td>
                    <td>{d == null ? <span className="muted">—</span> : (
                      <span style={{ color: d > 0 ? '#3B6D11' : d < 0 ? '#B43A2A' : '#6B7280', fontWeight: 600, fontSize: 12 }}>
                        {d > 0 ? `▲ +${d}` : d < 0 ? `▼ ${d}` : '±0'}</span>)}</td>
                    <td className="muted">{s.certifiable ?? '—'} / {(s.files ?? 0).toLocaleString()}</td>
                    {/* This table is WHERE the 2026-07-30 report was formed: a one-folder scan and
                        a whole-Drive scan of the same account sat in adjacent rows, both labelled
                        "drive", their file counts (1 and 8) side by side in the column left of
                        here. Nothing distinguished them, so the pair read as an estate that lost
                        seven documents. The scope chip is that distinction. It also warns the
                        reader off the "change" column, whose delta across two different scopes is
                        arithmetic on two different populations. */}
                    <td className="muted">{s.source}{scopeChip(s.scope) && (
                      <> <span className={`scopechip${scopeChip(s.scope).narrow ? ' narrow' : ''}`}
                               title={scopeSentence(s.scope, s.files ?? 0) || undefined}>
                        {scopeChip(s.scope).text}</span></>
                    )}</td>
                    <td onClick={(e) => e.stopPropagation()}><TraceChip scanId={s.id} kind="session" label="trace" /></td>
                  </tr>
                )
              })}
            </tbody>
          </table></div>
        </section>
      )}

      <PiiPanel scanId={run.id} />

      <div className="chartrow">
        <section className="panel"><h2>Compliance status <span className="muted" style={{ fontWeight: 400 }}>· click to drill in</span></h2><Donut segments={statusSegments(run, files)} caption="documents" onPick={pickStatus} /><Insight text={INS.status} /></section>
        <section className="panel"><h2>Findings by severity <span className="muted" style={{ fontWeight: 400 }}>· blocking findings</span></h2>
          {severity.length ? <Bars items={severity} onPick={pickSeverity} /> : <p className="muted">No blocking findings.</p>}
          {advisoryFindings > 0 && (
            <p className="muted" style={{ fontSize: 11.5, margin: '8px 0 0' }}>
              Plus <b>{advisoryFindings}</b> advisory finding{advisoryFindings === 1 ? '' : 's'} (review-recommended),
              not counted above — they are raised for a human to look at and never block certification.
              The estate holds <b>{allFindings}</b> findings in total.
            </p>
          )}
          <Insight text={INS.severity} />
        </section>
      </div>

      <div className="chartrow">
        <section className="panel"><h2>Top WCAG violations</h2><WordCloud items={wcCloud} /><Insight text={INS.wcag} /></section>
        <section className="panel"><h2>Documents by department <span className="muted" style={{ fontWeight: 400 }}>· {orgName}</span></h2><Bars items={byDept} cols="150px 1fr 28px" /><Insight text={INS.dept} /></section>
      </div>

      <div className="muted" style={{ margin: '20px 0 2px' }}>Compliance by dimension · scores, severity &amp; WCAG level <span style={{ fontWeight: 400 }}>· click a bar to drill in</span></div>
      <div className="chartrow">
        <section className="panel"><h2>Average score by department <span className="muted" style={{ fontWeight: 400 }}>· /100</span></h2><Bars items={scoreByDept} max={100} cols="150px 1fr 34px" onPick={(it) => { const fs = files.filter((f) => f.department === it.label); setSeg({ title: it.value == null ? `${it.label} · not yet scored` : `${it.label} · avg ${it.value} / 100`, subtitle: `${fs.length} documents`, files: fs }) }} />
          {deptAllUnassigned && <p className="muted" style={{ fontSize: 11.5, margin: '8px 0 0' }}>Every document is “Unassigned”: the source system reports no department, and the filename heuristic placed none of them. This is one estate-wide average, not a departmental comparison.</p>}
          <Insight text={INS.scoreByDept} /></section>
        <section className="panel"><h2>Average score by owner seniority <span className="muted" style={{ fontWeight: 400 }}>· /100</span></h2>
          {noSeniorityData
            ? <p className="muted">No owner seniority recorded for these documents — the source system did not report an owner, so there is nothing to break the scores down by. This is a gap in the metadata, not a score of zero.</p>
            : <><Bars items={scoreBySeniority} max={100} cols="100px 1fr 34px" onPick={(it) => { const fs = files.filter((f) => f.seniority === it.label); setSeg({ title: it.value == null ? `${it.label}-owned · not yet scored` : `${it.label}-owned · avg ${it.value} / 100`, subtitle: `${fs.length} documents`, files: fs }) }} /><Insight text={INS.scoreBySeniority} /></>}
        </section>
      </div>
      <div className="chartrow">
        <section className="panel"><h2>Findings by WCAG level <span className="muted" style={{ fontWeight: 400 }}>· all findings, blocking &amp; advisory</span></h2>{byLevel.length ? <Bars items={byLevel} cols="150px 1fr 30px" onPick={(it) => { const fs = files.filter((f) => (f.issues || []).some((i) => (levelOfFinding(i) || 'unknown') === it.lvl)); setSeg({ title: it.lvl === 'unknown' ? 'Findings whose criterion is not in the catalog' : `Level ${it.lvl} findings`, subtitle: `${fs.length} document(s)`, files: fs }) }} /> : <p className="muted">No open findings.</p>}<Insight text={INS.wcagLevel} /></section>
        <section className="panel"><h2>Documents by score band</h2><Bars items={scoreBands} cols="150px 1fr 30px" onPick={(it) => { const lo = it.label.startsWith('90') ? 90 : it.label.startsWith('50') ? 50 : it.label.startsWith('below') ? 0 : null; const fs = lo != null ? files.filter((f) => f.score != null && f.score >= lo && f.score <= (lo === 90 ? 100 : lo === 50 ? 89 : 49)) : files.filter((f) => f.score == null); setSeg({ title: it.label, subtitle: `${fs.length} document(s)`, files: fs }) }} /><Insight text={INS.scoreBand} /></section>
      </div>

      <div className="muted" style={{ margin: '20px 0 2px' }}>Inventory distribution</div>
      <div className="chartrow">
        <section className="panel"><h2>By source system</h2><Bars items={bySource} cols="118px 1fr 28px" onPick={(it) => { const fs = files.filter((f) => f.sourceName === it.label); setSeg({ title: `${it.label} · ${it.value} document${it.value !== 1 ? 's' : ''}`, subtitle: 'filtered by source', files: fs }) }} /><Insight text={INS.source} /></section>
        <section className="panel"><h2>By document type</h2><Bars items={byType} cols="62px 1fr 28px" onPick={(it) => { const fs = files.filter((f) => (f.type || '').toUpperCase() === it.label); setSeg({ title: `${it.label} documents · ${it.value} total`, subtitle: 'filtered by type', files: fs }) }} /><Insight text={INS.type} /></section>
      </div>

      <section className="panel">
        <h2>Compliance funnel · click a stage</h2>
        <div className="vfunnel">
          {stages.map((s) => (
            <button className="vfrow" key={s.label} onClick={() => onGo(s.go)} aria-label={`${s.label}${s.proj ? ' projected' : ''}: ${s.v.toLocaleString()} documents — open`}>
              <span className="vflabel">{s.label} {s.proj && <em>· proj</em>}</span>
              <span className="vfbar"><i style={{ width: on ? `${(s.v / maxN) * 100}%` : '0%', background: s.proj ? '#c4aecb' : '#7a5c8e' }} /></span>
              <span className="vfn">{s.v.toLocaleString()}</span>
            </button>
          ))}
        </div>
      </section>

      {trend.length > 1 && new Set(trend).size > 1 && (() => {
        // Compliance velocity: points/week from the FIRST to the LATEST scored scan,
        // using scanList's real completed_at (trend/trendDates above only carry a
        // display label, not a parseable date). A single outlier scan can't compute a
        // rate, so this only renders once there's a genuine time span to measure across.
        const scored = [...scanList].filter((s) => s.completed_at && s.avg_score != null)
          .sort((a, b) => a.completed_at.localeCompare(b.completed_at))
        let velocity = null, etaLabel = null
        if (scored.length >= 2) {
          const first = scored[0], last = scored[scored.length - 1]
          const days = (new Date(last.completed_at) - new Date(first.completed_at)) / 86400000
          if (days >= 1) {
            velocity = ((last.avg_score - first.avg_score) / days) * 7
            if (velocity > 0.05 && last.avg_score < 90) {
              const weeksToTarget = (90 - last.avg_score) / velocity
              const eta = new Date(Date.now() + weeksToTarget * 7 * 86400000)
              etaLabel = eta.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
            }
          }
        }
        return (
          <section className="panel">
            <h2>Compliance trend <span className="muted">· {trend.length} scans</span></h2>
            <Sparkline points={trend} labels={trendDates} width={620} height={104} />
            {velocity != null && (
              <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <span className="badge" style={{ background: velocity > 0 ? '#E7F0DC' : velocity < 0 ? '#FCEBEB' : '#EEEDEA',
                                                  color: velocity > 0 ? '#3B6D11' : velocity < 0 ? '#A32D2D' : 'var(--muted)' }}>
                  {velocity > 0 ? '↑' : velocity < 0 ? '↓' : '→'} {Math.abs(velocity).toFixed(1)} pts/week
                </span>
                <span className="muted" style={{ fontSize: 12.5 }}>
                  {etaLabel ? `at this pace, on track for 90/100 by ${etaLabel}` : velocity <= 0 ? 'flat or regressing — no projected path to 90/100 at this pace' : 'already at or above 90/100'}
                </span>
              </div>
            )}
          </section>
        )
      })()}

      {before != null && (
      <section className="panel"><h2>Compliance lift · projected after remediation</h2>
        <div className="lift">
          <div className="liftcol"><div className="liftnum" style={{ color: '#1F5FA8' }}>{before}</div><div className="muted">today · measured</div></div>
          <div className="liftarrow" aria-hidden="true">→</div>
          <div className="liftcol"><div className="liftnum" style={{ color: '#3B6D11' }}>{after}</div><div className="muted">after queued fixes <span style={{ fontSize: 10, opacity: 0.7 }}>(projected)</span></div></div>
          <div className="liftgain">+{after - before} pts</div>
        </div>
        <p className="muted">Projected estate score assuming all queued remediations are approved and pass re-validation — actual results may vary.</p>
      </section>
      )}
      </div>

      {seg &&<SegmentDrawer title={seg.title} subtitle={seg.subtitle} files={seg.files} onClose={() => setSeg(null)} onPickFile={setSelFile} />}
      {selFile && <FileDrawer file={selFile} scanId={run.id} onClose={() => setSelFile(null)} />}
    </>
  )
}

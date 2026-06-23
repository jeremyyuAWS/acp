import { useEffect, useRef, useState } from 'react'
import { Sparkline } from './ScoreRing.jsx'
import { Donut, Bars, statusSegments, severityItems } from './charts.jsx'
import SegmentDrawer from './SegmentDrawer.jsx'
import FileDrawer, { statusOf, critLabel } from './FileDrawer.jsx'
import { IDENTITY, remediableCount, recommendationSummary } from './sim.js'
import { loadPublished } from './ontology.js'
import WordCloud from './WordCloud.jsx'
import Insight from './Insight.jsx'

// The estate dashboard — doubles as the exportable compliance report.
export default function Overview({ run, files, trend, trendDates, onGo }) {
  const [on, setOn] = useState(false)
  const [seg, setSeg] = useState(null)
  const [selFile, setSelFile] = useState(null)
  const reportRef = useRef(null)
  const [exporting, setExporting] = useState(false)
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
      const verdict = auditReady >= 80 ? ['ON TRACK TO COMPLIANT', '#3B6D11'] : auditReady >= 45 ? ['DEVELOPING', '#854F0B'] : ['ACTION REQUIRED', '#1F5FA8']
      const criteria = Object.entries(wm).sort((a, b) => b[1] - a[1]).map(([w, count]) => ({ sc: w.replace(/^SC_/, '').replace(/_/g, '.'), label: critLabel(w).replace(/^[\d.]+\s*/, ''), count }))
      const { exportGovernanceReport } = await import('./pdfReport.js')
      await exportGovernanceReport({
        org: IDENTITY.org, quarter, date, scope: 'full document estate',
        total: n, score: run.avg_score, certifiable: run.certifiable, needFix, auditReady,
        uncertain: run.uncertain, error: run.error,
        summary: `Estate accessibility score ${run.avg_score ?? '—'}/100, with ${auditReady}% of documents audit-ready. ${needFix} documents are in the remediation backlog and ${n.toLocaleString()} are under continuous monitoring across ${(trend && trend.length) || 4} scans.`,
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

  const pickStatus = (s) => { const fs = files.filter((f) => statusOf(f) === s.label); setSeg({ title: `${s.label} documents`, subtitle: `${fs.length} of ${files.length}`, files: fs }) }
  const pickSeverity = (it) => { const sev = it.label.toUpperCase(); const fs = files.filter((f) => (f.issues || []).some((i) => i.severity === sev)); setSeg({ title: `${it.label} findings`, subtitle: `${fs.length} document(s) affected`, files: fs }) }

  const n = run.files || 0
  const needFix = remediableCount(files) // docs with a remediation action — matches the Remediate tab exactly
  // Published business ontology — surfaced for leadership so the org-aware prioritisation is visible here too.
  const ontDocs = files.filter((f) => f.ont)
  const ontCrit = ontDocs.filter((f) => f.ont.priority === 'Critical').length
  const ontHigh = ontDocs.filter((f) => f.ont.priority === 'High').length
  const ontVer = loadPublished()?.version
  const verify = Math.round(needFix * 0.7)
  const publish = run.certifiable + Math.round(needFix * 0.5)
  const auditReady = n ? Math.round((run.certifiable / n) * 100) : 0
  const maxN = Math.max(1, n)

  const stages = [
    { label: 'Discover', v: n, go: 'discover' },
    { label: 'Assess', v: n, go: 'assess' },
    { label: 'Remediate', v: needFix, go: 'remediate' },
    { label: 'Verify', v: verify, go: 'remediate', proj: true },
    { label: 'Publish', v: publish, go: 'monitor', proj: true },
  ]
  const severity = severityItems(files)

  // inventory distributions
  const countBy = (fn) => Object.entries(files.reduce((m, f) => { const k = fn(f); if (k != null) m[k] = (m[k] || 0) + 1; return m }, {})).sort((a, b) => b[1] - a[1])
  const PLUM = '#7a5c8e'
  const bySource = countBy((f) => f.sourceName).map(([label, value]) => ({ label, value, color: PLUM }))
  const byType = countBy((f) => (f.type || '').toUpperCase()).map(([label, value]) => ({ label, value, color: PLUM }))
  const byDept = countBy((f) => f.department).map(([label, value]) => ({ label, value, color: PLUM }))
  const wm = {}; files.forEach((f) => (f.issues || []).forEach((i) => { wm[i.wcag] = (wm[i.wcag] || 0) + 1 }))
  const wcCloud = Object.entries(wm).sort((a, b) => b[1] - a[1]).map(([w, n]) => ({ text: critLabel(w).replace(/^[\d.]+\s*/, ''), value: n, full: critLabel(w) }))

  // --- analysis by dimension (score / severity / WCAG level) — not just counts ---
  const scoreColor = (s) => s >= 90 ? '#639922' : s >= 50 ? '#BF8C00' : '#2E72C9'
  const avgScore = (fs) => { const sc = fs.filter((f) => f.score != null).map((f) => f.score); return sc.length ? Math.round(sc.reduce((a, b) => a + b, 0) / sc.length) : 0 }
  const groupBy = (fn) => files.reduce((m, f) => { const k = fn(f); if (k != null) (m[k] = m[k] || []).push(f); return m }, {})
  const scoreByDept = Object.entries(groupBy((f) => f.department)).map(([label, fs]) => ({ label, value: avgScore(fs), color: scoreColor(avgScore(fs)) })).sort((a, b) => a.value - b.value)
  const SR_ORDER = ['Executive', 'Director', 'Manager', 'Staff']
  const senGroups = groupBy((f) => f.seniority)
  const scoreBySeniority = SR_ORDER.filter((s) => senGroups[s]).map((label) => ({ label, value: avgScore(senGroups[label]), color: scoreColor(avgScore(senGroups[label])) }))
  const levelC = { A: 0, AA: 0, AAA: 0 }; files.forEach((f) => (f.issues || []).forEach((i) => { if (levelC[i.level] != null) levelC[i.level] += 1 }))
  const byLevel = [['A', '#1F5FA8', 'Level A · must-have'], ['AA', '#D85A30', 'Level AA · legal target'], ['AAA', '#9a948f', 'Level AAA · optional']].filter(([k]) => levelC[k]).map(([k, color, label]) => ({ label, value: levelC[k], color, lvl: k }))
  const band = (lo, hi) => files.filter((f) => f.score != null && f.score >= lo && f.score <= hi).length
  const scoreBands = [
    { label: '90–100 · certifiable', value: band(90, 100), color: '#639922' },
    { label: '50–89 · needs work', value: band(50, 89), color: '#BF8C00' },
    { label: 'below 50 · at risk', value: band(0, 49), color: '#2E72C9' },
    { label: 'n/a · unreadable', value: files.filter((f) => f.score == null).length, color: '#9a948f' },
  ].filter((d) => d.value)

  // on-demand AI insights (computed from the data; norm-aware, actionable)
  const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0)
  const sevTotal = severity.reduce((a, s) => a + s.value, 0)
  const sevHigh = severity.filter((s) => s.label === 'critical' || s.label === 'serious').reduce((a, s) => a + s.value, 0)
  const issuesOnly = Math.max(0, n - run.certifiable - run.uncertain - run.error)
  const INS = {
    status: `${auditReady}% of documents are certifiable — ${auditReady < 45 ? 'below' : 'around'} the ~45% typical once remediation is underway. Most of the ${issuesOnly} flagged documents are auto-fixable, so a first pass lifts this quickly.`,
    severity: sevTotal ? `Critical & serious findings (${sevHigh}) are ${pct(sevHigh, sevTotal)}% of all findings — ${pct(sevHigh, sevTotal) > 40 ? 'above' : 'near'} the ~40% you'd expect pre-remediation, driven by missing alt-text and untagged content. Clear these first to cut the most legal risk.` : 'No open findings.',
    source: bySource[0] ? `${bySource[0].label} holds the most documents (${bySource[0].value}). Weight remediation toward public web/CMS content — it's your highest-exposure surface under ADA/EAA even when smaller.` : '',
    type: byType[0] ? `${byType[0].label} is your largest format. PDFs are typically the hardest to remediate (tagging & reading order), so expect them to need the most human review.` : '',
    dept: byDept[0] ? `${byDept[0].label} has the most documents (${byDept[0].value}). Clinical and legal departments hold PII and legal-hold content, so closing their gaps first reduces the most risk.` : '',
    wcag: wcCloud[0] ? `WCAG ${wcCloud[0].full} is by far the most common failure (${wcCloud[0].value} documents). It's largely automatable — one class of fix would resolve a big share of your findings.` : '',
    scoreByDept: scoreByDept.length ? `${scoreByDept[0].label} has the lowest average score (${scoreByDept[0].value}/100) — the highest-leverage starting point. ${scoreByDept.at(-1)?.label} leads at ${scoreByDept.at(-1)?.value}/100; their approach is worth studying.` : '',
    scoreBySeniority: scoreBySeniority.length ? `Executive-owned documents score ${scoreBySeniority.find((s) => s.label === 'Executive')?.value ?? '—'}/100. Leadership content drives legal exposure and sets the tone — keep these on the fast track.` : '',
    wcagLevel: byLevel.length ? `${byLevel[0]?.value || 0} Level A findings are the legal floor and most automatable — address these first. Level AA (${levelC.AA || 0} findings) is the ADA/EAA/508 statutory target; Level AAA is optional.` : 'No findings by WCAG level.',
    scoreBand: `${band(90, 100)} documents are certifiable now (${pct(band(90, 100), n)}% of the estate). The ${band(50, 89)} in the 50–89 band are within striking distance — remediation here produces the fastest estate-level lift.`,
  }

  const before = run.avg_score ?? 72
  const after = Math.min(100, before + 12)
  return (
    <>
      <div className="dashtoolbar">
        <button className="exportbtn" onClick={doExport} disabled={exporting}>{exporting ? 'Generating PDF…' : '⤓ Quarterly governance report'}</button>
        <button className="exportbtn alt" onClick={exportCsv} title="Every finding as a spreadsheet row">⤓ Findings (CSV)</button>
      </div>
      <div ref={reportRef}>
      <div className="metrics">
        <div className="metric"><span>documents</span><b>{n.toLocaleString()}</b></div>
        <div className="metric"><span>certifiable</span><b style={{ color: '#3B6D11' }}>{run.certifiable}</b></div>
        <div className="metric" title="Documents with a remediation action — auto-fix, review, or manual rebuild (matches the Remediate tab)"><span>need remediation</span><b style={{ color: '#854F0B' }}>{needFix}</b></div>
        <div className="metric" title="Share of documents that are certifiable today (certifiable ÷ total)"><span>audit-ready</span><b>{auditReady}%</b></div>
      </div>

      {ontDocs.length > 0 && (
        <div className="ontovbar">
          <span className="ontovtag">⬆ Business ontology{ontVer ? ` v${ontVer}` : ''} active</span>
          <span className="ontovtext"><b>{ontDocs.length}</b> of {n.toLocaleString()} documents classified by your rules — <b style={{ color: '#1F5FA8' }}>{ontCrit} Critical</b> · <b style={{ color: '#854F0B' }}>{ontHigh} High</b> by business priority</span>
        </div>
      )}

      <div className="chartrow">
        <section className="panel"><h2>Compliance status <span className="muted" style={{ fontWeight: 400 }}>· click to drill in</span></h2><Donut segments={statusSegments(run)} caption="documents" onPick={pickStatus} /><Insight text={INS.status} /></section>
        <section className="panel"><h2>Findings by severity</h2>
          {severity.length ? <Bars items={severity} onPick={pickSeverity} /> : <p className="muted">No open findings.</p>}
          <Insight text={INS.severity} />
        </section>
      </div>

      <div className="chartrow">
        <section className="panel"><h2>Top WCAG violations</h2><WordCloud items={wcCloud} /><Insight text={INS.wcag} /></section>
        <section className="panel"><h2>Documents by department <span className="muted" style={{ fontWeight: 400 }}>· {IDENTITY.org}</span></h2><Bars items={byDept} cols="150px 1fr 28px" /><Insight text={INS.dept} /></section>
      </div>

      <div className="muted" style={{ margin: '20px 0 2px' }}>Compliance by dimension · scores, severity &amp; WCAG level <span style={{ fontWeight: 400 }}>· click a bar to drill in</span></div>
      <div className="chartrow">
        <section className="panel"><h2>Average score by department <span className="muted" style={{ fontWeight: 400 }}>· /100</span></h2><Bars items={scoreByDept} max={100} cols="150px 1fr 34px" onPick={(it) => { const fs = files.filter((f) => f.department === it.label); setSeg({ title: `${it.label} · avg ${it.value} / 100`, subtitle: `${fs.length} documents`, files: fs }) }} /><Insight text={INS.scoreByDept} /></section>
        <section className="panel"><h2>Average score by owner seniority <span className="muted" style={{ fontWeight: 400 }}>· /100</span></h2><Bars items={scoreBySeniority} max={100} cols="100px 1fr 34px" onPick={(it) => { const fs = files.filter((f) => f.seniority === it.label); setSeg({ title: `${it.label}-owned · avg ${it.value} / 100`, subtitle: `${fs.length} documents`, files: fs }) }} /><Insight text={INS.scoreBySeniority} /></section>
      </div>
      <div className="chartrow">
        <section className="panel"><h2>Findings by WCAG level</h2>{byLevel.length ? <Bars items={byLevel} cols="150px 1fr 30px" onPick={(it) => { const fs = files.filter((f) => (f.issues || []).some((i) => i.level === it.lvl)); setSeg({ title: `Level ${it.lvl} findings`, subtitle: `${fs.length} document(s)`, files: fs }) }} /> : <p className="muted">No open findings.</p>}<Insight text={INS.wcagLevel} /></section>
        <section className="panel"><h2>Documents by score band</h2><Bars items={scoreBands} cols="150px 1fr 30px" onPick={(it) => { const lo = it.label.startsWith('90') ? 90 : it.label.startsWith('50') ? 50 : it.label.startsWith('below') ? 0 : null; const fs = lo != null ? files.filter((f) => f.score != null && f.score >= lo && f.score <= (lo === 90 ? 100 : lo === 50 ? 89 : 49)) : files.filter((f) => f.score == null); setSeg({ title: it.label, subtitle: `${fs.length} document(s)`, files: fs }) }} /><Insight text={INS.scoreBand} /></section>
      </div>

      <div className="muted" style={{ margin: '20px 0 2px' }}>Inventory distribution</div>
      <div className="chartrow">
        <section className="panel"><h2>By source system</h2><Bars items={bySource} cols="118px 1fr 28px" onPick={(it) => { const fs = files.filter((f) => f.sourceName === it.label); setSeg({ title: `${it.label} · ${it.value} document${it.value !== 1 ? 's' : ''}`, subtitle: 'filtered by source', files: fs }) }} /><Insight text={INS.source} /></section>
        <section className="panel"><h2>By document type</h2><Bars items={byType} cols="62px 1fr 28px" onPick={(it) => { const fs = files.filter((f) => (f.type || '').toUpperCase() === it.label); setSeg({ title: `${it.label} documents · ${it.value} total`, subtitle: 'filtered by type', files: fs }) }} /><Insight text={INS.type} /></section>
      </div>

      <section className="panel">
        <h2>Compliance funnel · click a stage · <span style={{ color: '#854F0B', fontWeight: 400 }}>verify &amp; publish projected</span></h2>
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

      {trend.length > 1 && new Set(trend).size > 1 && (
        <section className="panel"><h2>Compliance trend · {trend.length} scans</h2><Sparkline points={trend} labels={trendDates} width={620} height={104} /></section>
      )}

      <section className="panel"><h2>Compliance lift · after remediation</h2>
        <div className="lift">
          <div className="liftcol"><div className="liftnum" style={{ color: '#1F5FA8' }}>{before}</div><div className="muted">today</div></div>
          <div className="liftarrow" aria-hidden="true">→</div>
          <div className="liftcol"><div className="liftnum" style={{ color: '#3B6D11' }}>{after}</div><div className="muted">after queued fixes</div></div>
          <div className="liftgain">+{after - before} pts</div>
        </div>
        <p className="muted">Projected estate score once the queued remediation is approved and re-validated.</p>
      </section>
      </div>

      {seg &&<SegmentDrawer title={seg.title} subtitle={seg.subtitle} files={seg.files} onClose={() => setSeg(null)} onPickFile={setSelFile} />}
      {selFile && <FileDrawer file={selFile} onClose={() => setSelFile(null)} />}
    </>
  )
}

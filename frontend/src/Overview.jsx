import { useEffect, useRef, useState } from 'react'
import { Sparkline } from './ScoreRing.jsx'
import { Donut, Bars, statusSegments, severityItems } from './charts.jsx'
import SegmentDrawer from './SegmentDrawer.jsx'
import FileDrawer, { statusOf, critLabel } from './FileDrawer.jsx'
import { IDENTITY } from './sim.js'
import WordCloud from './WordCloud.jsx'
import Insight from './Insight.jsx'
import { prefersReducedMotion } from './a11y.js'

const AUDIT = [
  ['auto-fix', 'alt-text added to figure 3', 'benefits-guide.pdf'],
  ['review', 'approved table-header fix', 'q3-board-deck.pptx'],
  ['publish', 'replaced in place', 'hr-policy-2026.docx'],
  ['re-scan', 'verified 100 / 100', 'onboarding.pdf'],
  ['archive', 'superseded version archived', '2019-policy-old.docx'],
  ['auto-fix', 'reading order corrected', 'annual-report.pdf'],
]
const ACTOR = { 'auto-fix': 'mova engine', review: 'A. Chen', publish: 'mova engine', 're-scan': 'mova engine', archive: 'mova engine' }
const ACOLOR = { 'auto-fix': '#1D9E75', review: '#854F0B', publish: '#185FA5', 're-scan': '#3B6D11', archive: '#5F5E5A' }

// The estate dashboard — doubles as the exportable compliance report (step 10).
export default function Overview({ run, files, trend, trendDates, onGo, ratified }) {
  const [on, setOn] = useState(false)
  const [seg, setSeg] = useState(null)
  const [selFile, setSelFile] = useState(null)
  const reportRef = useRef(null)
  const [exporting, setExporting] = useState(false)
  const [feed, setFeed] = useState(() => AUDIT.slice(0, 4).map((e, i) => ({ e, id: -i })))
  const nextId = useRef(1)
  useEffect(() => { const t = setTimeout(() => setOn(true), 80); return () => clearTimeout(t) }, [])
  useEffect(() => {
    if (prefersReducedMotion()) return
    const t = setInterval(() => setFeed((f) => [{ e: AUDIT[nextId.current % AUDIT.length], id: nextId.current++ }, ...f].slice(0, 6)), 2600)
    return () => clearInterval(t)
  }, [])
  const doExport = async () => {
    if (!reportRef.current) return
    setExporting(true)
    try { (await import('./exportPdf.js')).exportReportPDF(reportRef.current) }
    catch (e) { console.error('PDF export failed', e) }
    finally { setTimeout(() => setExporting(false), 600) }
  }

  const pickStatus = (s) => { const fs = files.filter((f) => statusOf(f) === s.label); setSeg({ title: `${s.label} documents`, subtitle: `${fs.length} of ${files.length}`, files: fs }) }
  const pickSeverity = (it) => { const sev = it.label.toUpperCase(); const fs = files.filter((f) => (f.issues || []).some((i) => i.severity === sev)); setSeg({ title: `${it.label} findings`, subtitle: `${fs.length} document(s) affected`, files: fs }) }

  const n = run.files || 0
  const needFix = Math.max(0, n - run.certifiable)
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
  }

  const before = run.avg_score ?? 72
  const after = Math.min(100, before + 12)
  return (
    <>
      <div className="dashtoolbar">
        <button className="exportbtn" onClick={doExport} disabled={exporting}>{exporting ? 'Generating PDF…' : '⤓ Export PDF report'}</button>
      </div>
      <div ref={reportRef}>
      <div className="metrics">
        <div className="metric"><span>documents</span><b>{n.toLocaleString()}</b></div>
        <div className="metric"><span>certifiable</span><b style={{ color: '#3B6D11' }}>{run.certifiable}</b></div>
        <div className="metric"><span>need remediation</span><b style={{ color: '#854F0B' }}>{needFix}</b></div>
        <div className="metric"><span>audit-ready</span><b>{auditReady}%</b></div>
      </div>

      <div className="chartrow">
        <section className="panel"><h2>Compliance status <span className="muted" style={{ fontWeight: 400 }}>· click to drill in</span></h2><Donut segments={statusSegments(run)} caption="documents" onPick={pickStatus} /><Insight text={INS.status} /></section>
        <section className="panel"><h2>Findings by severity</h2>
          {severity.length ? <Bars items={severity} onPick={pickSeverity} /> : <p className="muted">No open findings.</p>}
          <Insight text={INS.severity} />
        </section>
      </div>

      <div className="chartrow">
        <section className="panel"><h2>Top WCAG violations</h2><WordCloud items={wcCloud} /><Insight text={INS.wcag} /></section>
        <section className="panel"><h2>By department · {IDENTITY.org}</h2><Bars items={byDept} cols="150px 1fr 28px" /><Insight text={INS.dept} /></section>
      </div>

      <div className="muted" style={{ margin: '20px 0 2px' }}>Inventory distribution</div>
      <div className="chartrow">
        <section className="panel"><h2>By source system</h2><Bars items={bySource} cols="118px 1fr 28px" /><Insight text={INS.source} /></section>
        <section className="panel"><h2>By document type</h2><Bars items={byType} cols="62px 1fr 28px" /><Insight text={INS.type} /></section>
      </div>

      <section className="panel">
        <h2>Compliance funnel · click a stage · <span style={{ color: '#854F0B', fontWeight: 400 }}>verify &amp; publish projected</span></h2>
        <div className="vfunnel">
          {stages.map((s) => (
            <div className="vfrow" key={s.label} onClick={() => onGo(s.go)}>
              <span className="vflabel">{s.label} {s.proj && <em>· proj</em>}</span>
              <span className="vfbar"><i style={{ width: on ? `${(s.v / maxN) * 100}%` : '0%', background: s.proj ? '#c4aecb' : '#7a5c8e' }} /></span>
              <span className="vfn">{s.v.toLocaleString()}</span>
            </div>
          ))}
        </div>
      </section>

      {trend.length > 1 && new Set(trend).size > 1 && (
        <section className="panel"><h2>Compliance trend · {trend.length} scans</h2><Sparkline points={trend} labels={trendDates} width={620} height={104} /></section>
      )}

      <div className="chartrow">
        <section className="panel"><h2>Compliance lift · after remediation</h2>
          <div className="lift">
            <div className="liftcol"><div className="liftnum" style={{ color: '#A32D2D' }}>{before}</div><div className="muted">today</div></div>
            <div className="liftarrow" aria-hidden="true">→</div>
            <div className="liftcol"><div className="liftnum" style={{ color: '#3B6D11' }}>{after}</div><div className="muted">after queued fixes</div></div>
            <div className="liftgain">+{after - before} pts</div>
          </div>
          <p className="muted">Projected estate score once the queued remediation is approved and re-validated.</p>
        </section>
        <section className="panel"><h2>Compliance status</h2><Donut segments={statusSegments(run)} caption="documents" size={120} /></section>
      </div>

      <section className="panel">
        <h2>Audit trail · live <span className="livedot" aria-hidden="true" /></h2>
        <div className="auditfeed" role="log" aria-live="polite" aria-label="Audit trail">
          {ratified && ratified.total > 0 && (
            <div className="auditrow pinned">
              <span className="auditkind" style={{ background: '#EEEDFE', color: '#3C3489' }}>action plan</span>
              <span className="auditwhat">{ratified.total} recommendation{ratified.total === 1 ? '' : 's'} ratified · {ratified.auto} auto-fix, {ratified.assisted + ratified.review} to review</span>
              <span className="muted auditactor">you · just now</span>
            </div>
          )}
          {feed.map((row) => {
            const [kind, what, file] = row.e
            return (
              <div className="auditrow" key={row.id}>
                <span className="auditkind" style={{ background: ACOLOR[kind] + '1f', color: ACOLOR[kind] }}>{kind}</span>
                <span className="auditwhat">{what} · <span className="fname" style={{ fontSize: 12 }}>{file}</span></span>
                <span className="muted auditactor">{ACTOR[kind]}</span>
              </div>
            )
          })}
        </div>
        <p className="muted" style={{ marginTop: 10 }}>Immutable who / when / what / which-engine log — your ADA &amp; EAA evidence trail.</p>
      </section>
      </div>

      {seg &&<SegmentDrawer title={seg.title} subtitle={seg.subtitle} files={seg.files} onClose={() => setSeg(null)} onPickFile={setSelFile} />}
      {selFile && <FileDrawer file={selFile} onClose={() => setSelFile(null)} />}
    </>
  )
}

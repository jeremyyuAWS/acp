import { useEffect, useRef, useState } from 'react'
import { Donut, Bars, statusSegments } from './charts.jsx'
import { Sparkline } from './ScoreRing.jsx'
import { critLabel } from './FileDrawer.jsx'
import { IDENTITY } from './sim.js'
import Monitoring from './Monitoring.jsx'

const JOURNEY = [
  { label: 'discovered', s: 'done' }, { label: 'classified', s: 'done' },
  { label: 'assessed 67', s: 'done' }, { label: 'auto-fixed', s: 'done' },
  { label: 'reviewed', s: 'done' }, { label: 'verified 100', s: 'done' },
  { label: 'published', s: 'now' }, { label: 'monitored', s: 'todo' },
]
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

export default function Report({ run, files = [], trend = [], trendDates = [], certified = [] }) {
  const ref = useRef(null)
  const [on, setOn] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [feed, setFeed] = useState(() => AUDIT.slice(0, 4).map((e, i) => ({ e, id: -i })))
  const next = useRef(1)
  useEffect(() => { const t = setTimeout(() => setOn(true), 80); return () => clearTimeout(t) }, [])
  useEffect(() => {
    const t = setInterval(() => setFeed((f) => [{ e: AUDIT[next.current % AUDIT.length], id: next.current++ }, ...f].slice(0, 6)), 2600)
    return () => clearInterval(t)
  }, [])

  const certifiable = run ? run.certifiable : 0
  const published = certifiable + certified.length
  const before = run?.avg_score ?? 72
  const after = Math.min(100, before + 12)

  // compliance score by source
  const sm = {}
  files.forEach((f) => { const k = f.sourceName || f.source || '—'; sm[k] = sm[k] || { sum: 0, n: 0 }; if (f.score != null) { sm[k].sum += f.score; sm[k].n += 1 } })
  const bySource = Object.entries(sm).map(([name, v]) => ({ name, score: v.n ? Math.round(v.sum / v.n) : 0 })).sort((a, b) => b.score - a.score)

  // top failing WCAG criteria
  const cm = {}
  files.forEach((f) => (f.issues || []).forEach((i) => { cm[i.wcag] = (cm[i.wcag] || 0) + 1 }))
  const topCrit = Object.entries(cm).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([w, n]) => ({ label: critLabel(w), value: n, color: n >= 5 ? '#E24B4A' : '#F5B400' }))

  const doExport = async () => {
    if (!ref.current) return
    setExporting(true)
    try { (await import('./exportPdf.js')).exportReportPDF(ref.current) }
    catch (e) { console.error('PDF export failed', e) }
    finally { setTimeout(() => setExporting(false), 600) }
  }

  return (
    <>
      <Monitoring files={files} />

      <div className="dashtoolbar">
        <button className="exportbtn" onClick={doExport} disabled={exporting}>{exporting ? 'Generating PDF…' : '⤓ Export PDF report'}</button>
      </div>

      <div ref={ref} className="reportdoc">
        <div className="reporthead">
          <span className="logo"><span className="word">mova</span><span className="io"><span>io</span></span></span>
          <div>
            <div style={{ fontWeight: 600, fontSize: 15 }}>Accessibility compliance report</div>
            <div className="muted">{IDENTITY.org} · WCAG 2.1 AA · {(run?.completed_at || '').slice(0, 10) || 'estate-wide'}</div>
          </div>
        </div>

        <div className="metrics">
          <div className="metric"><span>estate score</span><b style={{ color: '#3B6D11' }}>{before}</b></div>
          <div className="metric"><span>published</span><b>{published}</b></div>
          <div className="metric"><span>documents</span><b>{run?.files ?? files.length}</b></div>
          <div className="metric"><span>next re-scan</span><b style={{ fontSize: 17 }}>in 6 days</b></div>
        </div>

        <div className="chartrow">
          <section className="panel"><h2>Estate compliance trend · {trend.length} scans</h2>
            {trend.length > 1 ? <Sparkline points={trend} labels={trendDates} width={360} height={100} /> : <p className="muted">Not enough history yet.</p>}
            <div className="muted" style={{ marginTop: 6 }}>{trend.length > 1 ? `${trend[0]} → ${trend[trend.length - 1]} over ${trend.length} scans` : ''}</div>
          </section>
          <section className="panel"><h2>Compliance status</h2>{run ? <Donut segments={statusSegments(run)} caption="documents" size={120} /> : null}</section>
        </div>

        <div className="chartrow">
          <section className="panel"><h2>Compliance score by source</h2>
            {bySource.map((s) => (
              <div key={s.name} className="critrow" style={{ gridTemplateColumns: '132px 1fr 34px' }}>
                <span className="critlabel" style={{ fontSize: 13 }}>{s.name}</span>
                <span className="track"><i style={{ width: on ? `${s.score}%` : '0%', background: s.score >= 80 ? '#639922' : s.score >= 50 ? '#F5B400' : '#F0524A', transition: 'width .9s ease' }} /></span>
                <span className="critn">{s.score}</span>
              </div>
            ))}
          </section>
          <section className="panel"><h2>Top failing WCAG criteria</h2>
            {topCrit.length ? <Bars items={topCrit} cols="120px 1fr 30px" /> : <p className="muted">No open findings.</p>}
          </section>
        </div>

        <div className="chartrow">
          <section className="panel"><h2>Compliance lift · after remediation</h2>
            <div className="lift">
              <div className="liftcol"><div className="liftnum" style={{ color: '#A32D2D' }}>{before}</div><div className="muted">before</div></div>
              <div className="liftarrow" aria-hidden="true">→</div>
              <div className="liftcol"><div className="liftnum" style={{ color: '#3B6D11' }}>{after}</div><div className="muted">after</div></div>
              <div className="liftgain">+{after - before} pts</div>
            </div>
            <p className="muted">Projected estate score once the queued fixes are approved and re-validated.</p>
          </section>
          <section className="panel"><h2>Document journey · benefits-guide.pdf</h2>
            <div className="journey">
              {JOURNEY.map((j) => (
                <span className={`jstep ${j.s === 'now' ? 'now' : j.s === 'todo' ? 'todo' : ''}`} key={j.label}>
                  {j.s === 'done' ? '✓' : j.s === 'now' ? '→' : '·'} {j.label}
                </span>
              ))}
            </div>
          </section>
        </div>

        <section className="panel">
          <h2>Audit trail · live <span className="livedot" aria-hidden="true" /></h2>
          <div className="auditfeed">
            {certified.map((c) => (
              <div className="auditrow pinned" key={'cert' + c.id}>
                <span className="auditkind" style={{ background: '#E7F0DC', color: '#3B6D11' }}>certified</span>
                <span className="auditwhat">remediated &amp; certified via Upload · <span className="fname" style={{ fontSize: 12 }}>{c.file}</span></span>
                <span className="muted auditactor">you · just now</span>
              </div>
            ))}
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
    </>
  )
}

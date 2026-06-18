import { useEffect, useRef, useState } from 'react'
import { Donut, Bars, statusSegments } from './charts.jsx'
import { Sparkline } from './ScoreRing.jsx'
import { critLabel, REC_STYLE } from './FileDrawer.jsx'
import { IDENTITY, recommendationSummary } from './sim.js'
import { WCAG } from './wcagCatalog.js'
import Logo from './Logo.jsx'
import { prefersReducedMotion } from './a11y.js'

const hrsFmt = (m) => m >= 90 ? `${(m / 60).toFixed(1)} hrs` : `${Math.round(m)} min`

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

export default function Report({ run, files = [], trend = [], trendDates = [], certified = [], ratified }) {
  const ref = useRef(null)
  const [on, setOn] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [feed, setFeed] = useState(() => AUDIT.slice(0, 4).map((e, i) => ({ e, id: -i })))
  const next = useRef(1)
  useEffect(() => { const t = setTimeout(() => setOn(true), 80); return () => clearTimeout(t) }, [])
  useEffect(() => {
    if (prefersReducedMotion()) return
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

  // remediation plan + WCAG coverage snapshot (for the exported report)
  const plan = files.length ? recommendationSummary(files) : null
  const planBars = plan ? plan.buckets.map((b) => ({ label: REC_STYLE[b.action][0], value: b.n, color: REC_STYLE[b.action][2] })) : []
  const cov = { live: WCAG.filter((r) => r.source === 'Shipped (demo)').length, partner: WCAG.filter((r) => r.source === 'Partner baseline').length, roadmap: WCAG.filter((r) => r.source === 'MDK net-new').length }

  const doExport = async () => {
    if (!ref.current) return
    setExporting(true)
    try { (await import('./exportPdf.js')).exportReportPDF(ref.current) }
    catch (e) { console.error('PDF export failed', e) }
    finally { setTimeout(() => setExporting(false), 600) }
  }

  return (
    <>
      <div className="dashtoolbar">
        <button className="exportbtn" onClick={doExport} disabled={exporting}>{exporting ? 'Generating PDF…' : '⤓ Export PDF report'}</button>
      </div>

      <div ref={ref} className="reportdoc">
        <div className="reporthead">
          <Logo />
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
          <section className="panel"><h2>Remediation plan</h2>
            {plan ? <>
              <div className="muted" style={{ marginBottom: 8 }}>≈ {hrsFmt(plan.remediateMin)} across {plan.remediableDocs} documents · {plan.autoPct}% fully automatic · saves ≈ {hrsFmt(plan.savedMin)} vs. manual</div>
              <Bars items={planBars} cols="132px 1fr 30px" />
              {ratified?.total > 0 && <p className="muted" style={{ marginTop: 8 }}>{ratified.total} recommendation{ratified.total === 1 ? '' : 's'} ratified by a reviewer.</p>}
            </> : <p className="muted">No plan available.</p>}
          </section>
          <section className="panel"><h2>WCAG 2.1 Level AA coverage</h2>
            <div className="metrics" style={{ marginBottom: 8 }}>
              <div className="metric"><span>live now</span><b style={{ color: '#3B6D11' }}>{cov.live}</b></div>
              <div className="metric"><span>partner</span><b style={{ color: '#3C3489' }}>{cov.partner}</b></div>
              <div className="metric"><span>roadmap</span><b style={{ color: '#854F0B' }}>{cov.roadmap}</b></div>
              <div className="metric"><span>criteria</span><b>87</b></div>
            </div>
            <p className="muted">Reporting target is <b>WCAG 2.1 Level AA</b> — the industry &amp; legal benchmark. Full Required A/AA conformance is ~3 weeks out (Claude-paced build).</p>
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
          <div className="auditfeed" role="log" aria-live="polite" aria-label="Audit trail">
            {ratified && ratified.total > 0 && (
              <div className="auditrow pinned">
                <span className="auditkind" style={{ background: '#EEEDFE', color: '#3C3489' }}>action plan</span>
                <span className="auditwhat">{ratified.total} recommendation{ratified.total === 1 ? '' : 's'} ratified · {ratified.auto} auto-fix, {ratified.assisted + ratified.review} to review, {ratified.archive} archive</span>
                <span className="muted auditactor">you · just now</span>
              </div>
            )}
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

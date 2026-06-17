import { useEffect, useState } from 'react'
import { Sparkline } from './ScoreRing.jsx'
import { Donut, Bars, statusSegments, severityItems } from './charts.jsx'

// Discover/Assess/Remediate are real (from the latest scan); Verify/Publish are projected.
export default function Overview({ run, files, trend, onGo }) {
  const [on, setOn] = useState(false)
  useEffect(() => { const t = setTimeout(() => setOn(true), 80); return () => clearTimeout(t) }, [])

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
    { label: 'Publish', v: publish, go: 'report', proj: true },
  ]
  const severity = severityItems(files)

  return (
    <>
      <div className="metrics">
        <div className="metric"><span>documents</span><b>{n.toLocaleString()}</b></div>
        <div className="metric"><span>certifiable</span><b style={{ color: '#3B6D11' }}>{run.certifiable}</b></div>
        <div className="metric"><span>need remediation</span><b style={{ color: '#854F0B' }}>{needFix}</b></div>
        <div className="metric"><span>audit-ready</span><b>{auditReady}%</b></div>
      </div>

      <div className="chartrow">
        <section className="panel"><h2>Compliance status</h2><Donut segments={statusSegments(run)} caption="documents" /></section>
        <section className="panel"><h2>Findings by severity</h2>
          {severity.length ? <Bars items={severity} /> : <p className="muted">No open findings.</p>}
        </section>
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
        <section className="panel"><h2>Compliance trend · {trend.length} scans</h2><Sparkline points={trend} width={560} height={72} /></section>
      )}

      <div className="muted" style={{ marginTop: 18, marginBottom: 8 }}>Outcomes you can prove</div>
      <div className="outcomes">
        <div className="outcome"><span className="oc">⚖</span><span className="ol">Legal risk (ADA / EAA)</span><span className="ov good">↓ 34%</span></div>
        <div className="outcome"><span className="oc">◷</span><span className="ol">Time to comply</span><span className="ov good">6× faster</span></div>
        <div className="outcome"><span className="oc">✓</span><span className="ol">Audit-ready evidence</span><span className="ov">{auditReady}%</span></div>
        <div className="outcome"><span className="oc">⛁</span><span className="ol">Remediation cost</span><span className="ov good">↓ 41%</span></div>
      </div>
    </>
  )
}

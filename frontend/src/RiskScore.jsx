import { severityItems } from './charts.jsx'
import { recommendationSummary } from './sim.js'

// Risk Scoring & Findings header for the "Risk & findings" view — the unified, leadership-
// readable summary the marketing card promises: compliance score, issue breakdown, WCAG
// success criteria, legal exposure, and remediation effort. Sits above the criterion graph.
export default function RiskScore({ run, files = [] }) {
  const sev = severityItems(files) // [{ label:'critical'|'serious'|..., value, color }]
  const wcagFailed = new Set()
  files.forEach((f) => (f.issues || []).forEach((i) => i.wcag && wcagFailed.add(i.wcag)))
  const rec = recommendationSummary(files)
  const publicCrit = files.filter((f) => (f.tags || []).some((t) => ['public-facing', 'high-traffic'].includes(t)) && (f.issues || []).some((i) => i.severity === 'CRITICAL')).length
  const exposure = publicCrit >= 8 ? ['High', '#1F5FA8'] : publicCrit >= 3 ? ['Elevated', '#854F0B'] : ['Moderate', '#3B6D11']
  const score = run?.avg_score ?? '—'
  const scoreColor = score >= 90 ? '#3B6D11' : score >= 50 ? '#854F0B' : '#1F5FA8'
  const effortH = Math.round((rec.remediateMin || 0) / 60)

  return (
    <section className="panel riskscore">
      <h2>Risk scoring &amp; findings <span className="muted" style={{ fontWeight: 400 }}>· unified view of what matters most</span></h2>
      <div className="risktiles">
        <div className="risktile">
          <span className="risklabel">Compliance score</span>
          <b className="riskbig" style={{ color: scoreColor }}>{score}<i>/100</i></b>
        </div>
        <div className="risktile">
          <span className="risklabel">Issue breakdown</span>
          <div className="riskbreak">
            {sev.length ? sev.map((s) => (
              <span className="riskchip" key={s.label}><i style={{ background: s.color }} />{s.value} {s.label}</span>
            )) : <span className="muted">No open findings</span>}
          </div>
        </div>
        <div className="risktile">
          <span className="risklabel">WCAG criteria failed</span>
          <b className="risknum">{wcagFailed.size}</b>
          <em className="risksub">success criteria with findings</em>
        </div>
        <div className="risktile">
          <span className="risklabel">Legal exposure</span>
          <b className="risknum" style={{ color: exposure[1] }}>{exposure[0]}</b>
          <em className="risksub">{publicCrit} public-facing critical</em>
        </div>
        <div className="risktile">
          <span className="risklabel">Remediation effort</span>
          <b className="risknum">{effortH}h</b>
          <em className="risksub">{rec.autoPct}% automated · {rec.remediableDocs} docs</em>
        </div>
      </div>
    </section>
  )
}

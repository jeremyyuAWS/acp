import { useEffect, useState } from 'react'
import { severityItems } from './charts.jsx'
import { fmtEffort, estimateEffortMin, EFFORT_BASIS } from './effort.js'
import { coreStats, scOfWcag } from './coreStats.js'
import { getCapability } from './api.js'
import { CAPABILITY_FALLBACK } from './capability.js'

// Severity penalty weights — MIRROR config/rubric.default.json ("severity_weights"). The backend
// computes the score as 100 − Σ(weight per finding); exposing the weights lets this card SHOW that
// arithmetic so the score is explainable, not arbitrary. Pinned against the config by
// riskScoreExplain.test.js so the two can never silently drift.
export const SEVERITY_WEIGHTS = { critical: 25, serious: 15, moderate: 8, minor: 3 }

const wrap = { marginTop: 6, fontSize: 11.5 }
const sumStyle = { cursor: 'pointer', color: 'var(--info-fg)', fontWeight: 600, listStyle: 'none' }
const rowStyle = { display: 'flex', justifyContent: 'space-between', gap: 12, padding: '2px 0', fontSize: 12 }
const dot = (c) => ({ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: c, marginRight: 6 })
const listStyle = { margin: '4px 0 0', paddingLeft: 16, fontSize: 12, lineHeight: 1.6 }

// Risk Scoring & Findings header — the unified, leadership-readable summary: compliance score,
// issue breakdown, WCAG success criteria, legal exposure, and remediation effort. Every number
// answers what / why / what-next: the score, legal exposure and remediation effort each carry a
// one-click "Why?" / "Plan" that shows the arithmetic or the reasoning behind them.
//
// The criteria-failed and remediation numbers read from coreStats() — the SAME document-core,
// capability-grounded lens the Assess tile leads with — so this panel reconciles with Assess
// exactly. It used to re-derive them from the SIM-only `f.rec` (0% automated on real scans) and
// count raw un-normalized criteria (drifting from what Assess showed); both are gone.
export default function RiskScore({ run, files = [] }) {
  // Remediation capability ({fmt: {sc: mode}}) — seeded with the bundled table so the auto-fixable
  // counts are correct synchronously, then refreshed from /capability (same pattern as AssessRunner).
  const [cap, setCap] = useState(CAPABILITY_FALLBACK)
  useEffect(() => {
    let on = true
    getCapability().then((r) => { if (on && r?.capability) setCap(r.capability) }).catch(() => {})
    return () => { on = false }
  }, [])

  const sev = severityItems(files) // [{ label:'critical'|'serious'|..., value, color }]
  // Failing criteria within the agreed scope — the same lens Assess leads with. `allFailed`
  // is the un-scoped count kept only for the "of N across all levels" context line, normalized so
  // the two wcag spellings (SC_1_1_1 / '1.1.1 name') don't double-count.
  const core = coreStats(files, cap)
  const allFailed = new Set()
  files.forEach((f) => (f.issues || []).forEach((i) => { const sc = scOfWcag(i.wcag); if (sc) allFailed.add(sc) }))
  const criticalN = sev.find((s) => s.label === 'critical')?.value || 0
  const publicCrit = files.filter((f) => (f.tags || []).some((t) => ['public-facing', 'high-traffic'].includes(t)) && (f.issues || []).some((i) => i.severity === 'CRITICAL')).length
  const exposure = publicCrit >= 8 ? ['High', 'var(--info-fg)'] : publicCrit >= 3 ? ['Elevated', 'var(--warn-fg)'] : ['Moderate', 'var(--success-fg)']
  const score = run?.avg_score ?? '—'
  const scoreColor = score >= 90 ? 'var(--success-fg)' : score >= 50 ? 'var(--warn-fg)' : 'var(--info-fg)'
  // Effort from the capability-grounded finding split (auto ≈ a minute, a person ≈ 35), NOT the
  // SIM-only rec (which is 0 on real scans). Still a planning estimate — rendered via fmtEffort
  // ("est.") with EFFORT_BASIS as the tooltip.
  const effortMin = estimateEffortMin({ auto: core.coreAutoFix, person: core.coreHuman })
  const effortEst = fmtEffort(effortMin)

  // Score explainability: 100 − Σ(count × weight). EXACT for a single scored document (the estate
  // score IS that document's); across an estate the score is the mean of per-doc scores, so the
  // rows are labelled as the severity contributions rather than an exact subtraction.
  const scoredDocs = files.filter((f) => f.score != null).length
  const penaltyRows = sev.map((s) => ({ ...s, weight: SEVERITY_WEIGHTS[s.label] || 0, sub: s.value * (SEVERITY_WEIGHTS[s.label] || 0) }))
  const totalPenalty = penaltyRows.reduce((n, r) => n + r.sub, 0)
  const rawScore = 100 - totalPenalty                    // pre-floor; the rubric floors at 0
  const floored = rawScore < 0                           // findings exceed 100 points
  const exactCalc = scoredDocs === 1 && typeof score === 'number' && Math.max(0, rawScore) === score

  return (
    <section className="panel riskscore">
      <h2>Risk scoring &amp; findings <span className="muted" style={{ fontWeight: 400 }}>· unified view of what matters most</span></h2>
      <div className="risktiles">
        <div className="risktile">
          <span className="risklabel">Compliance score</span>
          <b className="riskbig" style={{ color: scoreColor }}>{score}<i>/100</i></b>
          {sev.length > 0 && typeof score === 'number' && (
            <details style={wrap}>
              <summary style={sumStyle}>Why {score}?</summary>
              <div style={{ marginTop: 4 }}>
                <div style={rowStyle}><span>Start</span><b>100</b></div>
                {penaltyRows.map((r) => (
                  <div style={rowStyle} key={r.label}><span><i style={dot(r.color)} />{r.value} {r.label} × {r.weight}</span><b style={{ color: 'var(--warn-fg)' }}>−{r.sub}</b></div>
                ))}
                <div style={{ ...rowStyle, borderTop: '1px solid var(--line)', marginTop: 2, paddingTop: 4 }}>
                  <span>{exactCalc ? 'Score' : `Score · avg of ${scoredDocs} docs`}</span><b style={{ color: scoreColor }}>{score}{floored ? ' (floor)' : ''}</b>
                </div>
              </div>
              <p className="muted" style={{ margin: '5px 0 0', fontSize: 11 }}>WCAG 2.1 AA rubric · deterministic · each finding subtracts its severity weight from 100.{floored ? ` Findings total −${totalPenalty}, so the score floors at 0.` : ''}{!exactCalc && !floored ? ' Per-document scores are averaged across the estate.' : ''}</p>
            </details>
          )}
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
          <b className="risknum" title={`The ${core.coreCriteria} criteria with findings, of the ${core.scopeTotal} in this engagement's ${core.scopeLabel} — the same lens the Assess tab leads with. ${allFailed.size} distinct criteria fail across all WCAG levels, including ones outside that scope.`}>{core.coreCriteria}</b>
          <em className="risksub">of {core.scopeTotal} in {core.scopeLabel} · {allFailed.size} across all levels</em>
        </div>
        <div className="risktile">
          <span className="risklabel">Legal exposure</span>
          <b className="risknum" style={{ color: exposure[1] }}>{exposure[0]}</b>
          <em className="risksub">{criticalN} critical · {publicCrit ? `${publicCrit} public-facing` : 'none public-facing'} · {files.length} doc{files.length !== 1 ? 's' : ''}</em>
          <details style={wrap}>
            <summary style={sumStyle}>Why?</summary>
            <ul style={listStyle}>
              <li>{criticalN} critical finding{criticalN !== 1 ? 's' : ''}</li>
              <li>{publicCrit ? `${publicCrit} on public-facing content` : 'Not public-facing content'}</li>
              <li>{files.length} document{files.length !== 1 ? 's' : ''} in scope</li>
              <li className="muted">Policy-based estimate · no litigation modelled</li>
            </ul>
          </details>
        </div>
        <div className="risktile">
          <span className="risklabel">Remediation effort</span>
          <b className="risknum" title={EFFORT_BASIS}>{effortEst}</b>
          <em className="risksub">estimated · {core.autoPct}% auto-fixable · {core.coreFindings.toLocaleString()} finding{core.coreFindings !== 1 ? 's' : ''}</em>
          {core.coreFindings > 0 && (
            <details style={wrap}>
              <summary style={sumStyle}>Plan</summary>
              <div style={{ marginTop: 4 }}>
                <div style={rowStyle}><span><i style={dot('var(--success-fg)')} />ACP fixes automatically</span><b style={{ color: 'var(--success-fg)' }}>{core.coreAutoFix.toLocaleString()}</b></div>
                <div style={rowStyle}><span><i style={dot('var(--warn-fg)')} />A person reviews</span><b style={{ color: 'var(--warn-fg)' }}>{core.coreHuman.toLocaleString()}</b></div>
              </div>
              <p className="muted" style={{ margin: '5px 0 0', fontSize: 11 }}>Per finding, from the remediation-capability table (which fix each WCAG criterion supports on each file type) — the same split the Assess tab shows. Effort is a planning estimate, not a measurement.</p>
            </details>
          )}
        </div>
      </div>
    </section>
  )
}

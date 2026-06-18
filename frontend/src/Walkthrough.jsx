import { useState, useEffect } from 'react'

// Guided "watch it run" — walks ONE document through all 10 workflow stages with
// the agent's narration and a live score that climbs as it's remediated. Auto-
// advances; the user can pause, step, or restart. Pure demo theatre, no backend.
const DOC = 'open-enrollment-guide.pdf'
const STAGES = [
  { icon: '🔍', title: 'Discover & Inventory', agent: 'Crawled SharePoint · HR and indexed the document.', detail: `${DOC} — 24 pages · public-facing · 4,210 views/90d · owner A. Chen.` },
  { icon: '🏷️', title: 'Classify & Prioritize', agent: 'Auto-tagged by content, risk and exposure.', detail: 'Tags: public-facing · high-traffic → high legal exposure under ADA / EAA, prioritized.' },
  { icon: '🗂️', title: 'Retain / Archive / Delete', agent: 'Checked lifecycle before spending any effort.', detail: 'Active, high-traffic, not superseded → keep & remediate (archiving would be wrong here).' },
  { icon: '📋', title: 'Assess Accessibility', agent: 'Ran the multi-engine scan (python/pdf + agentic).', detail: '3 findings detected across non-text content, structure and language.', score: 61 },
  { icon: '📊', title: 'Risk Scoring & Findings', agent: 'Scored each finding by user impact × reach.', detail: '1 critical · missing alt text  ·  1 serious · table headers  ·  1 moderate · undeclared language.', score: 61 },
  { icon: '⚡', title: 'Automated Remediation', agent: 'Auto-fixed the mechanical findings, then re-tagged.', detail: 'Generated alt text, set the document language, tagged headings & reading order.', score: 84 },
  { icon: '🙋', title: 'Human-in-the-Loop', agent: 'One fix was below the confidence threshold — escalated.', detail: 'Table-structure call routed to a reviewer · approved by A. Chen.', score: 90 },
  { icon: '🔁', title: 'Re-validate & Verify', agent: 'Re-ran every engine on the fixed document.', detail: '0 open findings — the fix is independently confirmed, not taken on trust.', score: 100 },
  { icon: '🚀', title: 'Publish / Replace / Archive', agent: 'Replaced the file in place and notified owners.', detail: 'Compliant version published back to SharePoint · prior version archived.' },
  { icon: '📡', title: 'Monitor & Report', agent: 'Placed under continuous monitoring.', detail: 'Re-scans on every edit · added to the immutable audit trail as ADA / EAA evidence.' },
]
const scoreColor = (s) => s >= 90 ? '#3B6D11' : s >= 60 ? '#B8860B' : '#A32D2D'

export default function Walkthrough({ onClose }) {
  const [step, setStep] = useState(0)
  const [playing, setPlaying] = useState(true)

  useEffect(() => {
    if (!playing) return
    if (step >= STAGES.length - 1) { setPlaying(false); return }
    const t = setTimeout(() => setStep((s) => Math.min(STAGES.length - 1, s + 1)), 2700)
    return () => clearTimeout(t)
  }, [step, playing])
  useEffect(() => {
    const h = (e) => { if (e.key === 'Escape') onClose(); if (e.key === 'ArrowRight') setStep((s) => Math.min(STAGES.length - 1, s + 1)); if (e.key === 'ArrowLeft') setStep((s) => Math.max(0, s - 1)) }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [onClose])

  const st = STAGES[step]
  let score = null
  for (let i = 0; i <= step; i++) if (STAGES[i].score != null) score = STAGES[i].score
  const done = step >= STAGES.length - 1
  const go = (i) => { setPlaying(false); setStep(Math.max(0, Math.min(STAGES.length - 1, i))) }

  return (
    <div className="wtoverlay" role="dialog" aria-label="Guided walkthrough" onClick={onClose}>
      <div className="wtmodal" onClick={(e) => e.stopPropagation()}>
        <div className="wthead">
          <div><b>Watch a document go end-to-end</b><span className="muted"> · {DOC}</span></div>
          <button className="covclose" aria-label="Close" onClick={onClose}>✕</button>
        </div>

        <div className="wtrail">
          {STAGES.map((s, i) => (
            <button key={i} className={`wtdot${i === step ? ' on' : ''}${i < step ? ' done' : ''}`} title={`${i + 1}. ${s.title}`} aria-label={s.title} onClick={() => go(i)}>
              {i < step ? '✓' : i + 1}
            </button>
          ))}
        </div>

        <div className="wtbody">
          <div className="wtstage" key={step}>
            <div className="wticon" aria-hidden="true">{st.icon}</div>
            <div className="wtstep">Step {step + 1} of {STAGES.length}</div>
            <h3 className="wttitle">{st.title}</h3>
            <div className="wtagent"><span className="wtagenttag">agent</span>{st.agent}</div>
            <div className="wtdetail">{st.detail}</div>
          </div>
          <div className="wtscore">
            <div className="wtscorelabel">compliance score</div>
            <div className="wtscoreval" style={{ color: score == null ? '#b7afbd' : scoreColor(score) }}>{score == null ? '—' : score}<span className="wtscoremax">/100</span></div>
            <div className="wtscorebar"><i style={{ width: `${score || 0}%`, background: score == null ? '#e0dae6' : scoreColor(score) }} /></div>
            {score === 100 && <div className="wtcertified">✓ certifiable</div>}
          </div>
        </div>

        <div className="wtfoot">
          <button className="ghost small" onClick={() => go(0)} title="Restart">↻ Restart</button>
          <div className="wtnav">
            <button className="ghost small" onClick={() => go(step - 1)} disabled={step === 0}>◀</button>
            <button className="wtplay" onClick={() => { if (done) go(0); else setPlaying((p) => !p) }}>{done ? '↻ Replay' : playing ? '⏸ Pause' : '▶ Play'}</button>
            <button className="ghost small" onClick={() => go(step + 1)} disabled={done}>▶</button>
          </div>
          <span className="muted" style={{ fontSize: 12 }}>{done ? 'published & monitored · certifiable' : 'auto-advancing…'}</span>
        </div>
      </div>
    </div>
  )
}

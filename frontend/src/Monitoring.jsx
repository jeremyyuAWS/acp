import { useEffect, useRef, useState } from 'react'
import { monitoringState } from './sim.js'

// Step 10 — continuous monitoring surface. Makes the "always-on" capability
// tangible: status, coverage SLA, remediation backlog, and a live drift/alert
// feed driven by simulated re-scans. Lives above the (static) PDF report.
const ALERT = {
  regression: ['▼', '#A32D2D', '#FCEBEB'], drift: ['◇', '#854F0B', '#FAEEDA'],
  threshold: ['⚠', '#993C1D', '#FAECE7'], 'new-doc': ['＋', '#185FA5', '#E7F0FB'],
  recerted: ['✓', '#3B6D11', '#E7F0DC'],
}
const hrs = (m) => m >= 90 ? `${(m / 60).toFixed(1)} hrs` : `${Math.round(m)} min`

export default function Monitoring({ files = [] }) {
  const m = monitoringState(files)
  const [shown, setShown] = useState(2)
  const tick = useRef(0)
  // reveal alerts one-by-one so the feed feels live
  useEffect(() => {
    setShown(2); tick.current = 0
    const t = setInterval(() => { tick.current += 1; setShown((s) => Math.min(m.alerts.length, s + 1)) }, 2400)
    return () => clearInterval(t)
  }, [m.alerts.length])

  return (
    <section className="monitor">
      <div className="monitorhead">
        <span className="monlive"><span className="livedot" aria-hidden="true" /> Continuous monitoring · ON</span>
        <span className="muted">re-scans {m.cadence} · last {m.lastRescan} · next {m.nextRescan}</span>
      </div>

      <div className="moncards">
        <div className="moncard"><span className="muted">Documents watched</span><b>{m.watchedDocs}</b><span className="muted">{m.watchedSources} sources</span></div>
        <div className="moncard"><span className="muted">Re-scan coverage · 7d</span><b style={{ color: '#3B6D11' }}>{m.coveragePct}%</b><span className="muted">{m.slaPct}% within SLA</span></div>
        <div className="moncard"><span className="muted">Public-facing · daily</span><b>{m.publicDaily}</b><span className="muted">scanned every 24h</span></div>
        <div className="moncard"><span className="muted">Remediation backlog</span><b>{hrs(m.backlogMin)}</b><span className="muted">{m.autoPct}% automatic · {m.backlogDocs} docs</span></div>
        <div className="moncard"><span className="muted">Alerts · 7d</span><b style={{ color: '#A32D2D' }}>{m.alerts.length}</b><span className="muted">drift &amp; regressions</span></div>
      </div>

      <div className="monsplit">
        <div className="monpanel">
          <h3>Live monitoring feed <span className="livedot" aria-hidden="true" /></h3>
          <div className="monfeed">
            {m.alerts.slice(0, shown).map((a, i) => {
              const [glyph, fg, bg] = ALERT[a.kind] || ALERT.drift
              return (
                <div className="monrow" key={a.kind + i}>
                  <span className="monicon" style={{ color: fg, background: bg }} aria-hidden="true">{glyph}</span>
                  <div className="monmain">
                    <div>{a.text}</div>
                    <div className="muted fname" style={{ fontSize: 12 }}>{a.doc} · {a.when}</div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
        <div className="monpanel">
          <h3>Active monitoring rules</h3>
          <ul className="monrules">
            {m.rules.map((r) => <li key={r}><span className="ruledot" aria-hidden="true" />{r}</li>)}
          </ul>
        </div>
      </div>
    </section>
  )
}

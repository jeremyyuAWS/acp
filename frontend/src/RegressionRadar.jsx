import { useState, useEffect } from 'react'
import { getScanDiff } from './api.js'
import { TraceChip } from './Transparency.jsx'

// Real drift detection (ADR 0009) — diffs the viewed scan against the prior one and surfaces
// documents that regressed (with the exact WCAG criterion that flipped pass→fail) or improved.
// No continuous-monitoring webhooks needed — it's computed from scan history we already store.
export default function RegressionRadar({ run, scanList = [] }) {
  const [diff, setDiff] = useState(null)
  const [loading, setLoading] = useState(false)
  const [showImproved, setShowImproved] = useState(false)
  const runId = run?.id

  useEffect(() => {
    if (!runId) { setDiff(null); return }
    let cancelled = false
    setLoading(true)
    getScanDiff(runId)
      .then((d) => { if (!cancelled) { setDiff(d); setLoading(false) } })
      .catch(() => { if (!cancelled) { setDiff(null); setLoading(false) } })
    return () => { cancelled = true }
  }, [runId])

  if (!runId || scanList.length < 2) return null      // need a prior scan to compare against
  const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '')

  if (loading && !diff) {
    return <section className="panel" style={{ marginBottom: 14 }}><h2 style={{ margin: 0 }}>Regression radar</h2><p className="muted" style={{ marginTop: 8 }}>Comparing to the previous scan…</p></section>
  }
  if (!diff || diff.no_baseline) return null
  const s = diff.summary || {}

  return (
    <section className="panel" style={{ marginBottom: 14 }}>
      <div className="proghd">
        <h2 style={{ margin: 0 }}>Regression radar <span className="muted" style={{ fontSize: 12 }}>· drift vs the scan from {fmtDate(diff.prev_at)}</span></h2>
        <div className="radarchips">
          <span className="rchip reg">⚠ {s.regressed} regressed</span>
          <span className="rchip imp">✓ {s.improved} improved</span>
          {s.new ? <span className="rchip neu">+{s.new} new</span> : null}
          {s.removed ? <span className="rchip rem">−{s.removed} removed</span> : null}
        </div>
      </div>

      {diff.regressed.length === 0 ? (
        <p className="muted" style={{ marginTop: 8 }}>✓ Nothing got worse since the last scan — no document lost conformance.</p>
      ) : (
        <div className="radarlist" style={{ marginTop: 10 }}>
          {diff.regressed.map((r) => (
            <div className="radarrow" key={r.file}>
              <div className="radarfile">
                <span className="fname">{r.file}</span>
                {r.broke?.length ? <div className="muted" style={{ fontSize: 11.5 }}>now failing: {r.broke.map((b) => `${b.sc} ${b.name}`).join(' · ')}</div> : null}
              </div>
              <span className="radardelta down">{r.prev}&nbsp;→&nbsp;{r.cur} <b>▼{Math.abs(r.delta)}</b></span>
              <TraceChip traceId={diff.cur_id} label="trace" />
            </div>
          ))}
        </div>
      )}

      {diff.improved.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <button className="ghost small" onClick={() => setShowImproved((v) => !v)}>{showImproved ? 'Hide' : 'Show'} {diff.improved.length} improved</button>
          {showImproved && (
            <div className="radarlist" style={{ marginTop: 8 }}>
              {diff.improved.map((r) => (
                <div className="radarrow" key={r.file}>
                  <div className="radarfile"><span className="fname">{r.file}</span></div>
                  <span className="radardelta up">{r.prev}&nbsp;→&nbsp;{r.cur} <b>▲{r.delta}</b></span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

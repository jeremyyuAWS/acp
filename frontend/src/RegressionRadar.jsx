import { useState, useEffect } from 'react'
import { getScanDiff } from './api.js'
import { TraceChip } from './Transparency.jsx'

// Mirrors FileDrawer's SEV map (not exported there) — same severity → color
// convention across the app.
const SEV = {
  CRITICAL: ['var(--info-bg)', 'var(--info-fg)'], SERIOUS: ['#E6EFFB', '#2A5E9E'],
  MODERATE: ['var(--warn-bg)', 'var(--warn-fg)'], MINOR: ['#F1EFE8', '#5F5E5A'],
}

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
          {/* Kept OUT of the removed chip on purpose. A document the scope excluded was not
              read; it did not leave the estate, and merging the two turns "we assess only Word
              documents" into "45 documents disappeared". */}
          {s.not_read ? <span className="rchip rem" title="Excluded by this scan's file-type scope — not read, not missing">{s.not_read} not read</span> : null}
          {s.incomparable ? <span className="rchip neu" title="Assessed against a different set of criteria, so the scores are not comparable">{s.incomparable} not comparable</span> : null}
        </div>
      </div>

      {/* SAID, not merely implied. Suppressing incomparable deltas without explaining why leaves
          a reader with a quiet radar and the conclusion that nothing changed — the same failure
          as reporting the scope change as improvement, arrived at from the other side. */}
      {diff.scope_changed ? (
        <p className="muted" style={{ marginTop: 8, fontSize: 12.5 }} role="status">
          The scan scope changed since {fmtDate(diff.prev_at)}.
          {s.incomparable ? ` ${s.incomparable} document${s.incomparable === 1 ? ' was' : 's were'} assessed against a different set of criteria, so ${s.incomparable === 1 ? 'its score is' : 'their scores are'} not compared here — a score only means something against the criteria it was measured on.` : ''}
          {s.not_read ? ` ${s.not_read} document${s.not_read === 1 ? '' : 's'} of other file types ${s.not_read === 1 ? 'was' : 'were'} not read this time.` : ''}
        </p>
      ) : null}

      {diff.regressed.length === 0 ? (
        <p className="muted" style={{ marginTop: 8 }}>
          {s.incomparable
            /* "Nothing got worse" is a claim about documents that were COMPARED. With every
               comparable document accounted for and others excluded, the honest sentence names
               what it covers rather than implying it covered everything. */
            ? `✓ Nothing got worse among the documents that could be compared.`
            : '✓ Nothing got worse since the last scan — no document lost conformance.'}
        </p>
      ) : (
        <div className="radarlist" style={{ marginTop: 10 }}>
          {diff.regressed.map((r) => (
            <div className="radarrow" key={r.file}>
              <div className="radarfile">
                <span className="fname">{r.file}</span>
                {r.broke?.length ? (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 3 }}>
                    {r.broke.map((b) => {
                      const [bg, fg] = SEV[b.severity] || SEV.MINOR
                      return (
                        <span key={b.sc} title={b.severity ? b.severity[0] + b.severity.slice(1).toLowerCase() : undefined}
                              style={{ fontSize: 11, padding: '1px 6px', borderRadius: 999, background: bg, color: fg, whiteSpace: 'nowrap' }}>
                          {b.sc} {b.name}
                        </span>
                      )
                    })}
                  </div>
                ) : null}
              </div>
              <span className="radardelta down">{r.prev}&nbsp;→&nbsp;{r.cur} <b>▼{Math.abs(r.delta)}</b></span>
              <TraceChip scanId={diff.cur_id} kind="file" file={r.file} label="trace" />
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

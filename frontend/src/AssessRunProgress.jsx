import { normalizeLive } from './liveAssessment.js'

// The Assess RUNNING screen (approved board assess-03). It replaces the mid-run KPI scoreboard
// (LiveAssessment.jsx, kept but no longer mounted here) with a single per-DOCUMENT focus card.
//
// WHY NOT A SCOREBOARD. Board 3's rule: "no metric renders mid-run — a partially-filled count of
// failures reads as a verdict, and there is no honest way to caption one mid-run." The KPIs the old
// panel showed live on the Overview now, where they fill in once a run has FINISHED and can be read
// as a result. Here, mid-run, the screen answers one question — which document is being worked, and
// how far through the estate we are — and says plainly that the results arrive at the end.
//
// EVERYTHING IS FROM THE LIVE SNAPSHOT, or omitted. Document position and the progress bar come from
// completed-vs-eligible; the current file and step from the live_queue "current" block; the ETA from
// rolling throughput. The board's finer per-document checklist (pages/elements read, checks-done)
// needs per-document progress the snapshot does not carry yet, so it is not invented — the current
// STEP is shown instead of a fabricated checklist.
//
// STOP LIVES HERE NOW, board-exact. It used to stay in App.jsx's shared scan-progress banner (also
// used by Discover), duplicating nothing but sitting in the wrong place relative to the board. App
// now suppresses ITS OWN Stop specifically while this card is the one showing (view === 'assess' &&
// assessPhase === 'running') and passes the same cancel handler down as `onStop` — so there is still
// exactly one Stop control on screen at any moment, just the board's chosen one.

function stepLabel(cur) {
  if (!cur) return null
  if (cur.action) return cur.action
  if (cur.criterionName) return `Checking ${cur.criterionName}`
  if (cur.criterion) return `Checking ${cur.criterion}`
  if (cur.text) return cur.text
  return 'Assessing this document'
}

export default function AssessRunProgress({ snapshot, throughput, onStop }) {
  const m = normalizeLive(snapshot)
  if (!m.available) return null

  const total = m.totals.eligible || m.totals.discovered || 0
  const completed = snapshot && snapshot.kpis ? Number(snapshot.kpis.completed) || 0 : 0
  // The document IN FLIGHT is the one after those completed — 1-based, clamped so it never reads
  // "Document 23 of 22" on the last frame before the run leaves 'running'.
  const position = total ? Math.min(total, completed + (m.active ? 1 : 0)) : completed
  const pct = total ? Math.min(100, Math.round((completed / total) * 100)) : 0
  const cur = m.queue ? m.queue.current : null
  const eta = throughput && (throughput.etaText || (throughput.calibrating ? 'estimating…' : null))

  return (
    <section className="assess-run-progress" role="region" aria-label="Assessment in progress"
             style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <header style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        {/* aria-live on the heading only: the document-of-N line changes every couple of seconds and
            a live region over it would spam a screen reader; the phase and the estate size do not. */}
        <h3 style={{ margin: 0, fontSize: 16 }}>
          Assessing {total.toLocaleString()} document{total === 1 ? '' : 's'}
        </h3>
        {m.phaseLabel && <span className="muted" style={{ fontSize: 13 }}>{m.phaseLabel}</span>}
      </header>

      <div className="assess-run-card" style={{ border: '1px solid var(--line,#e4e8ec)', borderRadius: 12,
                                                padding: '14px 16px', background: 'var(--panel,#fff)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap',
                      alignItems: 'baseline' }}>
          <div style={{ fontSize: 15, fontWeight: 650 }} aria-live="polite">
            {total ? `Document ${position} of ${total.toLocaleString()}` : 'Preparing…'}
          </div>
          {eta && <div className="muted" style={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}>
            {eta}
          </div>}
        </div>

        {/* Indeterminate (shimmer) when nothing has scored yet — a 0-width bar looks
            broken; the shimmer says "working" without claiming false precision. */}
        <div className={pct === 0 ? 'track indeterminate' : 'track'}
             style={{ height: 8, borderRadius: 999, background: 'var(--line,#eceff2)',
                      overflow: 'hidden', margin: '10px 0' }}>
          <i style={{ display: 'block', height: '100%', width: `${pct}%`, background: '#4A2C4D',
                      transition: 'width .3s' }} />
        </div>

        {cur ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            {cur.file && (
              <div style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12.5 }}>
                {cur.file}
              </div>
            )}
            <div className="muted" style={{ fontSize: 12.5 }} aria-live="polite">{stepLabel(cur)}</div>
          </div>
        ) : (
          <div className="muted" style={{ fontSize: 12.5 }}>
            {(m.queue && m.queue.laneLabel) || 'Preparing…'}
          </div>
        )}
      </div>

      {/* Stop, board-exact placement: the button beside the sentence explaining what it does, not a
          bare icon in a corner. Only while the run is actually active — a finished/cancelled run has
          nothing left to stop, and offering the control anyway would invite a confusing no-op click. */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
        {onStop && m.active && (
          <button type="button" className="ghost small" onClick={onStop}
                  title="Stop this run — documents already assessed are kept">
            Stop
          </button>
        )}
        {/* The board's central promise. Not a caption on a number — there is no number to caption. */}
        <p className="muted" style={{ fontSize: 12.5, margin: 0, lineHeight: 1.6, flex: '1 1 260px' }}>
          Results appear when the run finishes, not before — a half-populated count of failures reads as a
          verdict, and there is no honest way to caption one mid-run. Stopping keeps the documents already
          assessed; nothing is written back to your drive at any point.
        </p>
      </div>
    </section>
  )
}

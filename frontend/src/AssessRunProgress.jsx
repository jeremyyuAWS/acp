import { useState, useEffect } from 'react'
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

function fmtElapsedSecs(s) {
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const r = s % 60
  return r ? `${m}m ${r}s` : `${m}m`
}

// One preparation step row: icon (✓ / pulsing dot / ○), label, right-aligned detail.
function PrepStep({ label, detail, status }) {
  return (
    <div role="listitem" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <span style={{ width: 16, flexShrink: 0, display: 'flex', alignItems: 'center',
                     justifyContent: 'center' }} aria-hidden="true">
        {status === 'done' && <span style={{ color: 'var(--green,#1a7f45)', fontSize: 13.5 }}>✓</span>}
        {status === 'active' && <span className="prep-pulse" />}
        {status === 'pending' && <span style={{ color: 'var(--muted)', fontSize: 13 }}>○</span>}
      </span>
      <span style={{ flex: 1, fontSize: 13.5,
                     color: status === 'pending' ? 'var(--muted)' : 'var(--ink)' }}>
        {label}
      </span>
      {detail && (
        <span className="muted" style={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}>
          {detail}
        </span>
      )}
    </div>
  )
}

// Four-step preparation checklist shown while 0 files have completed (indeterminate phase).
// Each step infers its completion state from real snapshot data — no fabricated percentages.
// One pulsing dot (●) marks the active step; done steps show ✓; not-yet-started show ○.
function PrepChecklist({ m, total, completed, processing, elapsed }) {
  const q = m.queue
  const workers = q ? q.workers : null
  const workersCount = workers ? (workers.busy + (workers.idle ?? 0)) : 0
  const workersMax = workers ? workers.max : null

  const invDone = total > 0
  // Workers considered fully started when all slots are filled, OR when some workers are
  // active and the queue already has work (they are busy enough to have queued items).
  const workersDone = workers !== null && (
    (workersMax !== null && workersCount >= workersMax) ||
    (workersCount > 0 && q && (q.queued > 0 || q.inFlight > 0))
  )
  const queueDone = !!(q && (q.queued > 0 || q.inFlight > 0))

  const phases = [
    {
      label: 'Validating scan inventory',
      done: invDone,
      detail: invDone ? `${total.toLocaleString()} files` : null,
    },
    {
      label: 'Starting assessment workers',
      done: workersDone,
      detail: workersMax != null
        ? `${workersCount} of ${workersMax} ready`
        : workersCount > 0 ? `${workersCount} ready` : null,
    },
    {
      label: 'Building the document queue',
      done: queueDone,
      detail: q && q.queued > 0 ? `${q.queued.toLocaleString()} queued` : null,
    },
    // Generic on purpose: several workers open and assess documents concurrently, so naming a
    // single "first" document is both visually noisy and quickly inaccurate. The count at right
    // is the authoritative live snapshot and updates until the determinate view takes over.
    {
      label: 'Assessment in progress',
      done: false,
      detail: `${completed.toLocaleString()} of ${total.toLocaleString()} completed${processing > 0 ? ` · ${processing.toLocaleString()} processing` : ''}`,
    },
  ]

  const firstActiveIdx = phases.findIndex(p => !p.done)
  const steps = phases.map((p, i) => ({
    ...p,
    status: p.done ? 'done' : i === firstActiveIdx ? 'active' : 'pending',
  }))

  const isStalled = elapsed >= 120

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
                    gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 14.5, fontWeight: 650 }}>Preparing assessment</div>
        {/* elapsed ticks every second — aria-hidden keeps it out of the polite live region */}
        <div className="muted" style={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}
             aria-hidden="true">
          {fmtElapsedSecs(elapsed)} elapsed
        </div>
      </div>

      {/* aria-live on the step list so completions are announced politely, not on every tick. */}
      <div aria-live="polite" aria-atomic="false" role="list" aria-label="Preparation steps"
           style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
        {steps.map((s, i) => <PrepStep key={i} {...s} />)}
      </div>

      {isStalled && (
        <p role="alert" style={{ margin: '12px 0 0', fontSize: 12.5, lineHeight: 1.5,
                                 color: 'var(--amber,#92400e)' }}>
          Preparation is taking longer than usual.
          {workers && workersMax != null && ` ${workersCount} of ${workersMax} workers are ready.`}
          {' '}No documents have been assessed yet.
        </p>
      )}
    </div>
  )
}

export default function AssessRunProgress({ snapshot, throughput, onStop }) {
  const m = normalizeLive(snapshot)

  const total = m.available ? (m.totals.eligible || m.totals.discovered || 0) : 0
  const completed = m.available && snapshot?.kpis ? Number(snapshot.kpis.completed) || 0 : 0
  const processing = m.available && snapshot?.kpis ? Number(snapshot.kpis.processing) || 0 : 0
  const pct = total ? Math.min(100, Math.round((completed / total) * 100)) : 0
  const isPreparing = m.available && pct === 0
  const isFinished = total > 0 && completed >= total

  // Elapsed seconds since this screen first appeared — stops ticking once real progress begins.
  const [startedAt] = useState(() => Date.now())
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    if (!isPreparing) return
    setElapsed(Math.round((Date.now() - startedAt) / 1000))
    const t = setInterval(() => setElapsed(Math.round((Date.now() - startedAt) / 1000)), 1000)
    return () => clearInterval(t)
  }, [isPreparing, startedAt])

  if (!m.available) return null

  const cur = m.queue ? m.queue.current : null
  const eta = throughput && (throughput.etaText || (throughput.calibrating ? 'estimating…' : null))

  return (
    <section className="assess-run-progress" role="region"
             aria-label={isFinished ? 'Assessment complete' : 'Assessment in progress'}
             style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div className="assess-run-card" style={{ border: '1px solid var(--line,#e4e8ec)', borderRadius: 12,
                                                padding: '14px 16px', background: 'var(--panel,#fff)' }}>
        {isPreparing ? (
          <PrepChecklist m={m} total={total} completed={completed}
                         processing={processing} elapsed={elapsed} />
        ) : (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                          gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
              <strong style={{ fontSize: 14.5 }}>{isFinished ? 'Assessment complete' : 'Assessing documents'}</strong>
              <span role="status" style={{ fontSize: 11.5, padding: '2px 7px', borderRadius: 4,
                                            display: 'inline-flex', alignItems: 'center', gap: 5,
                                            background: 'var(--green-bg,#f0f7e6)', color: 'var(--green,#3B6D11)',
                                            border: '1px solid var(--green-line,#a8cf7a)' }}>
                {!isFinished && <span className="pulsedot" aria-hidden="true" />}
                {isFinished ? 'Updates complete' : 'Live'}
              </span>
            </div>

            <progress value={completed} max={Math.max(1, total)}
                      aria-label={`Assessment: ${completed.toLocaleString()} of ${total.toLocaleString()} documents complete`}
                      aria-valuetext={`${completed.toLocaleString()} of ${total.toLocaleString()} documents complete`}
                      style={{ width: '100%', height: 7, display: 'block', marginBottom: 12 }} />

            <div role="list" aria-live="polite" aria-atomic="false"
                 style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
              <PrepStep status="done" label="Validated assessment scope"
                        detail={`${total.toLocaleString()} documents`} />
              <PrepStep status="done" label="Started assessment workers"
                        detail={m.queue?.workers?.max != null
                          ? `${m.queue.workers.max.toLocaleString()} ready`
                          : 'Workers ready'} />
              <PrepStep status={isFinished ? 'done' : 'active'} label="Opened and assessed documents"
                        detail={`${completed.toLocaleString()} of ${total.toLocaleString()} complete${processing > 0 ? ` · ${processing.toLocaleString()} processing` : ''}`} />
              <PrepStep status={isFinished ? 'done' : 'pending'} label="Finalized conformance results"
                        detail={isFinished ? 'Complete' : eta || 'After all documents finish'} />
            </div>

            {!isFinished && (cur || m.queue?.laneLabel) && (
              <div style={{ borderTop: '1px solid var(--line,#e4e8ec)', paddingTop: 12, marginTop: 14,
                            fontSize: 12.5, lineHeight: 1.5 }}>
                <span className="muted">Processing now: </span>
                {cur?.file && <strong style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}>{cur.file}</strong>}
                <span className="muted">{cur?.file ? ' · ' : ''}{stepLabel(cur) || m.queue?.laneLabel}</span>
              </div>
            )}
          </>
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

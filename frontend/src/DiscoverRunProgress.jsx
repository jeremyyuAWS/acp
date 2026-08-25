import { useState, useEffect, useRef } from 'react'

// The Discover RUNNING screen: a per-step checklist showing what the discovery agent is doing.
// This replaces the generic scan-progress banner on the Discover tab so the screen stays scoped
// to inventory — no assessment workers, no WCAG content, no findings. The steps are derived from
// real backend phase data; no percentage is fabricated.
//
// STOP LIVES HERE on the Discover tab. App.jsx suppresses the shared .scanprog banner's Stop
// when view === 'discover', and passes the same cancel handler here as `onStop`.

function fmtElapsedSecs(s) {
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const r = s % 60
  return r ? `${m}m ${r}s` : `${m}m`
}

// How many steps (from the front of STEPS) are DONE at each backend phase.
// Steps: 0=connected, 1=listing, 2=metadata, 3=classifying, 4=lifecycle, 5=saving
const PHASE_DONE_COUNT = {
  queued: 0, connecting: 0,
  discovering: 1,
  reading: 2,
  tagging: 3,
  analysing: 4,
  scoring: 5, finalizing: 5,
  done: 6,
}

const STEPS = [
  { key: 'connected', label: 'Connected to source' },
  { key: 'listing', label: 'Listing folders and files' },
  { key: 'metadata', label: 'Reading document metadata' },
  { key: 'classifying', label: 'Classifying document types' },
  { key: 'lifecycle', label: 'Applying lifecycle rules' },
  { key: 'saving', label: 'Saving inventory' },
]

function DiscoverStep({ label, detail, status }) {
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

export default function DiscoverRunProgress({ progress, busy, onStop, sources, inv = null, onReview = null }) {
  const [startedAt] = useState(() => Date.now())
  const [elapsed, setElapsed] = useState(0)
  const [stalledSecs, setStalledSecs] = useState(0)
  const lastTickRef = useRef(Date.now())

  // Reset stall counter whenever a new progress payload arrives.
  useEffect(() => {
    lastTickRef.current = Date.now()
    setStalledSecs(0)
  }, [progress])

  useEffect(() => {
    if (!busy || !progress) return
    setElapsed(Math.round((Date.now() - startedAt) / 1000))
    const t = setInterval(() => {
      setElapsed(Math.round((Date.now() - startedAt) / 1000))
      setStalledSecs(Math.round((Date.now() - lastTickRef.current) / 1000))
    }, 1000)
    return () => clearInterval(t)
  }, [busy, progress, startedAt])

  if (!progress) return null

  const phase = progress.phase || 'queued'
  const isDone = phase === 'done'
  const isStopped = !busy && !isDone
  const filesFound = progress.files_found || 0
  const doneCount = PHASE_DONE_COUNT[phase] ?? 0

  // "Connected to X" uses the source name when exactly one source is connected.
  const sourceName = sources && sources.length === 1 ? sources[0].name : null

  // Distinct lifecycle rules applied so far — shown on the lifecycle step once inventory arrives.
  const lifecycleRulesCount = inv?.rows
    ? new Set(inv.rows.map((r) => r.lifecycle_rule_id).filter(Boolean)).size
    : null

  const steps = STEPS.map((s, i) => {
    let detail = null
    if (s.key === 'listing' && filesFound > 0) detail = `${filesFound.toLocaleString()} found`
    if (s.key === 'lifecycle' && lifecycleRulesCount) detail = `${lifecycleRulesCount} rule${lifecycleRulesCount === 1 ? '' : 's'} applied`
    return {
      ...s,
      label: i === 0 && sourceName ? `Connected to ${sourceName}` : s.label,
      status: i < doneCount ? 'done' : i === doneCount ? 'active' : 'pending',
      detail,
    }
  })

  // No progress ticks for 90 s — connection may be lost.
  const showStalledWarning = busy && !isDone && stalledSecs >= 90
  // After 90 s with no files found during listing, the source likely has many folders to walk.
  const showLongRunningHint = !showStalledWarning && elapsed >= 90 && filesFound === 0 && phase === 'discovering'
  // Lifecycle evaluation can take 30+ s on large inventories.
  const showLifecycleSlowHint = !showStalledWarning && elapsed >= 30 && phase === 'lifecycle'

  // Stopped / failed card — scan ended before completion (user stop, auth failure, network drop).
  // The active step is demoted to pending so no pulse dot appears on a stopped scan.
  if (isStopped) {
    const errorMsg = progress.error ?? null
    const totalFiles = inv?.total ?? (filesFound > 0 ? filesFound : 0)
    const stoppedSteps = steps.map((s) => ({ ...s, status: s.status === 'active' ? 'pending' : s.status }))
    return (
      <section className="discover-run-progress" role="region" aria-label="Discovery stopped"
               style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 20 }}>
        <div className="assess-run-card" style={{ border: '1px solid var(--line,#e4e8ec)', borderRadius: 12,
                                                  padding: '14px 16px', background: 'var(--panel,#fff)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
                        gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
            <div style={{ fontSize: 14.5, fontWeight: 650 }}>
              {errorMsg ? 'Discovery could not complete' : 'Discovery stopped'}
            </div>
            <span className="muted" style={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}>
              {fmtElapsedSecs(elapsed)}
            </span>
          </div>
          <div role="list" aria-label="Discovery steps"
               style={{ display: 'flex', flexDirection: 'column', gap: 9, marginBottom: 14 }}>
            {stoppedSteps.map(({ key, ...rest }) => <DiscoverStep key={key} {...rest} />)}
          </div>
          <div style={{ borderTop: '1px solid var(--line,#e4e8ec)', paddingTop: 12,
                        fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.6 }}>
            {errorMsg && (
              <div style={{ color: 'var(--red,#c0392b)', marginBottom: 4 }}>{errorMsg}</div>
            )}
            {totalFiles > 0 && (
              <div>{totalFiles.toLocaleString()} file{totalFiles !== 1 ? 's' : ''} catalogued.</div>
            )}
            <div>Partial inventory retained. No documents were assessed or changed.</div>
          </div>
          {onReview && totalFiles > 0 && (
            <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
              <button type="button" className="ghost small" onClick={onReview}>
                Review partial inventory
              </button>
            </div>
          )}
        </div>
      </section>
    )
  }

  // Completion summary replaces the active checklist once all steps are done.
  if (isDone) {
    const totalFiles = inv?.total ?? filesFound
    return (
      <section className="discover-run-progress" role="region" aria-label="Discovery complete"
               style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 20 }}>
        <div className="assess-run-card" style={{ border: '1px solid var(--line,#e4e8ec)', borderRadius: 12,
                                                  padding: '14px 16px', background: 'var(--panel,#fff)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
                        gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
            <div style={{ fontSize: 14.5, fontWeight: 650 }}>Discovery complete</div>
            <span className="muted" style={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}>
              {fmtElapsedSecs(elapsed)}
            </span>
          </div>
          <div aria-live="polite" aria-atomic="false" role="list" aria-label="Discovery steps"
               style={{ display: 'flex', flexDirection: 'column', gap: 9, marginBottom: 14 }}>
            {steps.map(({ key, ...rest }) => <DiscoverStep key={key} {...rest} />)}
          </div>
          <div style={{ borderTop: '1px solid var(--line,#e4e8ec)', paddingTop: 12,
                        fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.6 }}>
            {totalFiles > 0
              ? <div>{totalFiles.toLocaleString()} files discovered. No documents were assessed or changed.</div>
              : <div>No documents were assessed or changed.</div>
            }
          </div>
          {onReview && (
            <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
              <button type="button" className="ghost small" onClick={onReview}>Review inventory</button>
            </div>
          )}
        </div>
      </section>
    )
  }

  return (
    <section className="discover-run-progress" role="region" aria-label="Discovery in progress"
             style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 20 }}>
      <div className="assess-run-card" style={{ border: '1px solid var(--line,#e4e8ec)', borderRadius: 12,
                                                padding: '14px 16px', background: 'var(--panel,#fff)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
                      gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 14.5, fontWeight: 650 }}>Discovering documents</div>
          <div className="muted" style={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}
               aria-hidden="true">
            {fmtElapsedSecs(elapsed)} elapsed
          </div>
        </div>

        <div aria-live="polite" aria-atomic="false" role="list" aria-label="Discovery steps"
             style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
          {steps.map(({ key, ...rest }) => <DiscoverStep key={key} {...rest} />)}
        </div>

        {showStalledWarning && (
          <p role="alert" style={{ fontSize: 12.5, margin: '12px 0 0', lineHeight: 1.5,
                                   color: 'var(--red,#c0392b)' }}>
            Discovery appears stalled — no progress for {stalledSecs}s. The source may be unreachable.
          </p>
        )}
        {showLongRunningHint && (
          <p className="muted" style={{ fontSize: 12.5, margin: '12px 0 0', lineHeight: 1.5 }}>
            This source contains many folders — discovery is still active.
          </p>
        )}
        {showLifecycleSlowHint && (
          <p className="muted" style={{ fontSize: 12.5, margin: '12px 0 0', lineHeight: 1.5 }}>
            Lifecycle evaluation is taking longer than usual.
          </p>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
        {onStop && busy && (
          <button type="button" className="ghost small" onClick={onStop}
                  title="Stop this scan — inventory collected so far is kept">
            Stop
          </button>
        )}
        <p className="muted" style={{ fontSize: 12.5, margin: 0, lineHeight: 1.6, flex: '1 1 260px' }}>
          Stopping keeps the inventory collected so far. No documents are opened, assessed, moved,
          or changed in the source.
        </p>
      </div>
    </section>
  )
}

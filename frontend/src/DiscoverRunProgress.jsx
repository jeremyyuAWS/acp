import { useState, useEffect } from 'react'

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
  const isActive = status === 'active'
  return (
    <div role="listitem" aria-current={isActive ? 'step' : undefined}
         style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <span style={{ width: 16, flexShrink: 0, display: 'flex', alignItems: 'center',
                     justifyContent: 'center' }}>
        {status === 'done' && (
          <span role="img" aria-label="Completed"
                style={{ color: 'var(--green,#1a7f45)', fontSize: 13.5 }}>✓</span>
        )}
        {status === 'active' && (
          <span className="prep-pulse" role="status" aria-label="In progress" />
        )}
        {status === 'pending' && (
          <span role="img" aria-label="Not started"
                style={{ color: 'var(--muted)', fontSize: 13 }}>○</span>
        )}
      </span>
      <span style={{ flex: 1, fontSize: 13.5,
                     fontWeight: isActive ? 600 : undefined,
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

export default function DiscoverRunProgress({ progress, busy, onStop, sources, inv = null }) {
  const [startedAt] = useState(() => Date.now())
  const [elapsed, setElapsed] = useState(0)
  const [stopping, setStopping] = useState(false)

  useEffect(() => {
    if (!busy || !progress) return
    setElapsed(Math.round((Date.now() - startedAt) / 1000))
    const t = setInterval(() => setElapsed(Math.round((Date.now() - startedAt) / 1000)), 1000)
    return () => clearInterval(t)
  }, [busy, progress, startedAt])

  if (!busy || !progress) return null

  const phase = progress.phase || 'queued'
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

  // After 90 s with no files found during listing, the source likely has many folders to walk.
  const showLongRunningHint = elapsed >= 90 && filesFound === 0 && phase === 'discovering'

  function handleStop() {
    setStopping(true)
    onStop?.()
  }

  return (
    <section className="discover-run-progress" role="region" aria-label="Discovery in progress"
             style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 20 }}>
      <div className="assess-run-card" style={{ border: '1px solid var(--line,#e4e8ec)', borderRadius: 12,
                                                padding: '14px 16px', background: 'var(--panel,#fff)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 14.5, fontWeight: 650 }}>Discovering documents</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <span className="muted" style={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}
                  aria-hidden="true">
              {fmtElapsedSecs(elapsed)} elapsed
            </span>
            {onStop && busy && (
              <button type="button" className="ghost small" onClick={handleStop}
                      disabled={stopping}
                      title="Stop discovery — partial inventory will be retained">
                {stopping ? 'Stopping…' : 'Stop'}
              </button>
            )}
          </div>
        </div>

        <div aria-live="polite" aria-atomic="false" role="list" aria-label="Discovery steps"
             style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
          {steps.map(({ key, ...rest }) => <DiscoverStep key={key} {...rest} />)}
        </div>

        {showLongRunningHint && (
          <p className="muted" style={{ fontSize: 12.5, margin: '12px 0 0', lineHeight: 1.5 }}>
            This source contains many folders — discovery is still active.
          </p>
        )}
      </div>

      <p className="muted" style={{ fontSize: 12.5, margin: 0, lineHeight: 1.6 }}>
        Partial inventory will be retained. Source files will not be changed.
      </p>
    </section>
  )
}

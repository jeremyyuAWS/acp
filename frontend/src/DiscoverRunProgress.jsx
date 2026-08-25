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

function n(count) { return count.toLocaleString() }

const ASSESSABLE_CLASSES = new Set(['slide-deck', 'text-document', 'pdf-document', 'spreadsheet', 'web-page'])

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

// Each step has a present-progressive label (active/pending) and a past-tense label (done).
const STEPS = [
  { key: 'connected',   label: 'Connected to source',       labelDone: 'Connected to source' },
  { key: 'listing',     label: 'Listing folders and files',  labelDone: 'Listed folders and files' },
  { key: 'metadata',    label: 'Reading document metadata',  labelDone: 'Read document metadata' },
  { key: 'classifying', label: 'Classifying document types', labelDone: 'Classified document types' },
  { key: 'lifecycle',   label: 'Applying lifecycle rules',   labelDone: 'Applied lifecycle rules' },
  { key: 'saving',      label: 'Saving inventory',           labelDone: 'Saved inventory' },
]

function DiscoverStep({ label, kpi, status }) {
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
      {kpi && (
        <span className="muted" aria-hidden="true"
              style={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}>
          {kpi}
        </span>
      )}
    </div>
  )
}

export default function DiscoverRunProgress({ progress, busy, onStop, sources, inv = null, onReview, onContinue }) {
  const [startedAt] = useState(() => Date.now())
  const [elapsed, setElapsed] = useState(0)
  const [stopping, setStopping] = useState(false)

  useEffect(() => {
    if (!busy || !progress) return
    setElapsed(Math.round((Date.now() - startedAt) / 1000))
    const t = setInterval(() => setElapsed(Math.round((Date.now() - startedAt) / 1000)), 1000)
    return () => clearInterval(t)
  }, [busy, progress, startedAt])

  if (!progress) return null
  const phase = progress.phase || 'queued'
  const isDone = phase === 'done'
  if (!busy && !isDone) return null

  const filesFound = progress.files_found || 0
  const doneCount = PHASE_DONE_COUNT[phase] ?? 0

  // Source label substitution and KPI.
  const sourceName = sources && sources.length === 1 ? sources[0].name : null
  const sourceCount = sources ? sources.length : null

  // Lifecycle stats from inventory: matched = files with any rule applied, unchanged = the rest.
  const lifecycleMatchedCount = inv?.rows != null
    ? inv.rows.filter((r) => r.lifecycle_rule_id != null).length
    : null
  const lifecycleUnchangedCount = (lifecycleMatchedCount !== null && inv?.total != null)
    ? inv.total - lifecycleMatchedCount
    : null

  // Metadata completeness: complete = owner and source_modified both present.
  const metadataCompleteCount = inv?.rows != null
    ? inv.rows.filter((r) => r.owner != null && r.source_modified != null).length
    : null
  const metadataIncompleteCount = (metadataCompleteCount !== null && inv?.total != null)
    ? inv.total - metadataCompleteCount
    : null

  // Classification stats: assessable = doc types we can evaluate for WCAG.
  const assessableCount = inv?.rows != null
    ? inv.rows.filter((r) => ASSESSABLE_CLASSES.has(r.doc_class)).length
    : null
  const unsupportedCount = (assessableCount !== null && inv?.total != null)
    ? inv.total - assessableCount
    : null

  const steps = STEPS.map((s, i) => {
    const status = i < doneCount ? 'done' : i === doneCount ? 'active' : 'pending'
    const displayLabel = i === 0 && sourceName
      ? `Connected to ${sourceName}`
      : (status === 'done' ? s.labelDone : s.label)

    let kpi = null
    if (status === 'done') {
      if (s.key === 'connected' && sourceCount) {
        kpi = sourceCount === 1 ? '1 source' : `${sourceCount} sources`
      }
      if (s.key === 'listing' && filesFound > 0) {
        kpi = `${n(filesFound)} files found`
      }
      if (s.key === 'metadata' && metadataCompleteCount !== null && metadataIncompleteCount !== null) {
        kpi = `${n(metadataCompleteCount)} complete · ${n(metadataIncompleteCount)} incomplete`
      }
      if (s.key === 'classifying' && assessableCount !== null && unsupportedCount !== null) {
        kpi = `${n(assessableCount)} assessable · ${n(unsupportedCount)} unsupported`
      }
      if (s.key === 'lifecycle' && lifecycleMatchedCount !== null && lifecycleUnchangedCount !== null) {
        kpi = `${n(lifecycleMatchedCount)} matched · ${n(lifecycleUnchangedCount)} unchanged`
      }
    }
    if (status === 'active' && s.key === 'listing' && filesFound > 0) {
      kpi = `${n(filesFound)} files found so far`
    }

    return { ...s, label: displayLabel, status, kpi }
  })

  // After 90 s with no files found during listing, the source likely has many folders to walk.
  const showLongRunningHint = elapsed >= 90 && filesFound === 0 && phase === 'discovering'

  // The step label that is currently active — used in a dedicated live region so phase transitions
  // are announced once, without the per-tick KPI counts that aria-hidden="true" suppresses above.
  const activeStepLabel = steps.find((s) => s.status === 'active')?.label ?? null

  function handleStop() {
    setStopping(true)
    onStop?.()
  }

  // Completion summary replaces the active checklist once all steps are done.
  if (isDone) {
    const totalFiles = inv?.total ?? filesFound
    const matched = lifecycleMatchedCount ?? 0
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
            <div>{n(totalFiles)} files discovered · {n(matched)} matched lifecycle rules</div>
            {assessableCount !== null && (
              <div>{n(assessableCount)} assessable · {n(unsupportedCount)} unsupported</div>
            )}
            <div>No documents were assessed or changed.</div>
          </div>
          {(onReview || onContinue) && (
            <div style={{ display: 'flex', gap: 10, marginTop: 14, flexWrap: 'wrap' }}>
              {onReview && (
                <button type="button" className="ghost small" onClick={onReview}>
                  Review inventory
                </button>
              )}
              {onContinue && (
                <button type="button" className="primary small" onClick={onContinue}>
                  Continue to Assessment →
                </button>
              )}
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

        {/* Announces phase transitions to screen readers without repeating per-tick KPI counts.
            Placed after the step list so step label text in the list is found first by indexOf. */}
        <span className="sr-only" role="status" aria-live="polite" aria-atomic="true">
          {activeStepLabel ? `Step in progress: ${activeStepLabel}` : null}
        </span>

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

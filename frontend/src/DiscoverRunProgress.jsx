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
  lifecycle: 4,
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

// Per-step explanation of what stop does while that step is active.
const STOP_HINTS = {
  listing:     'Stops at the next folder — files listed so far will be kept.',
  metadata:    'Metadata already read will be kept; unread files will be skipped.',
  classifying: 'Classification results so far will be kept.',
  lifecycle:   'Rules already applied will be kept.',
  saving:      'The inventory save will complete before stopping.',
}

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
  const foldersFound = progress.folders_found ?? null
  const doneCount = PHASE_DONE_COUNT[phase] ?? 0

  // Exception counters from schema_version 2+ progress payloads.
  const excInaccessible = progress.exc_inaccessible_file ?? null
  const excMetadataFailure = progress.exc_metadata_failure ?? null
  const excDeleted = progress.exc_deleted_during_scan ?? null
  const excMissingOptional = progress.exc_missing_optional ?? null
  const excMissingRequired = progress.exc_missing_required ?? null
  const totalExceptions = (excInaccessible ?? 0) + (excMetadataFailure ?? 0) + (excDeleted ?? 0)

  // Save-step outcome counts from schema_version 2+ done payloads.
  const saveNew = progress.save_new ?? null
  const saveUpdated = progress.save_updated ?? null
  const saveUnchanged = progress.save_unchanged ?? null
  const saveFailed = progress.save_failed ?? null

  // Lifecycle activity stats from schema_version 2+ done payloads.
  const rulesEnabled = progress.rules_enabled ?? null
  const filesEvaluated = progress.files_evaluated ?? null
  const lifecycleMatches = progress.lifecycle_matches ?? null
  const lcArchive = progress.lifecycle_archive ?? null
  const lcDelete = progress.lifecycle_delete ?? null
  const lcTagged = progress.lifecycle_tagged ?? null
  // Folder activity fields emitted in the post-BFS "discovering" event.
  const foldersVisited = progress.folders_visited ?? null
  const folderWorkersConfigured = progress.folder_workers_configured ?? null

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

  // Metadata completeness: prefer progress-payload fields (schema_version 2+) so a live or
  // deferred scan shows counts before the inventory is fully loaded. Falls back to inv-derived
  // counts for backends that predate this field.
  const metadataCompleteCount = progress.metadata_complete ?? (inv?.rows != null
    ? inv.rows.filter((r) => r.owner != null && r.source_modified != null).length
    : null)
  const metadataIncompleteCount = progress.metadata_incomplete ?? ((metadataCompleteCount !== null && inv?.total != null)
    ? inv.total - metadataCompleteCount
    : null)

  // Classification stats: 5-bucket breakdown from schema_version 2+ done payloads (PRD §6.4).
  const clsAssessable = progress.assessable ?? null
  const clsMetadataOnly = progress.metadata_only ?? null
  const clsUnsupported = progress.unsupported ?? null
  const clsEligibilityUnknown = progress.eligibility_unknown ?? null
  const clsExcluded = progress.excluded ?? null
  const hasClassStats = clsAssessable !== null

  // Fallback: inv-derived binary assessable / unsupported for old backends.
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
        kpi = foldersFound !== null
          ? `${n(filesFound)} files · ${n(foldersFound)} folders`
          : `${n(filesFound)} files found`
      }
      if (s.key === 'metadata') {
        const parts = []
        if (metadataCompleteCount !== null && metadataIncompleteCount !== null) {
          parts.push(`${n(metadataCompleteCount)} complete · ${n(metadataIncompleteCount)} incomplete`)
        }
        if (totalExceptions > 0) {
          const excParts = []
          if (excInaccessible) excParts.push(`${n(excInaccessible)} inaccessible`)
          if (excDeleted) excParts.push(`${n(excDeleted)} deleted`)
          if (excMetadataFailure) excParts.push(`${n(excMetadataFailure)} unreadable`)
          if (excParts.length) parts.push(excParts.join(' · '))
        }
        if (parts.length) kpi = parts.join(' — ')
      }
      if (s.key === 'classifying') {
        if (hasClassStats) {
          const parts = [
            clsAssessable > 0 && `${n(clsAssessable)} assessable`,
            clsMetadataOnly > 0 && `${n(clsMetadataOnly)} metadata-only`,
            clsUnsupported > 0 && `${n(clsUnsupported)} unsupported`,
            clsEligibilityUnknown > 0 && `${n(clsEligibilityUnknown)} eligibility unknown`,
            clsExcluded > 0 && `${n(clsExcluded)} excluded`,
          ].filter(Boolean)
          if (parts.length) kpi = parts.join(' · ')
        } else if (assessableCount !== null && unsupportedCount !== null) {
          kpi = `${n(assessableCount)} assessable · ${n(unsupportedCount)} not assessable`
        }
      }
      if (s.key === 'lifecycle') {
        if (rulesEnabled !== null) {
          // Use progress payload fields (schema_version 2+) — more accurate than inv-derived counts.
          const actionParts = [
            lcArchive > 0 && `${n(lcArchive)} Archive Candidate${lcArchive === 1 ? '' : 's'}`,
            lcDelete > 0 && `${n(lcDelete)} Delete Candidate${lcDelete === 1 ? '' : 's'}`,
            lcTagged > 0 && `${n(lcTagged)} tagged`,
          ].filter(Boolean)
          kpi = rulesEnabled === 0
            ? '— No enabled rules'
            : [`${n(rulesEnabled)} rules · ${n(lifecycleMatches)} matched`,
               ...actionParts].join(' · ')
        } else if (lifecycleMatchedCount !== null && lifecycleUnchangedCount !== null) {
          // Fallback for old backends that don't emit lifecycle stats.
          kpi = lifecycleMatchedCount === 0
            ? '— No enabled rules'
            : `${n(lifecycleMatchedCount)} matched · ${n(lifecycleUnchangedCount)} unchanged`
        }
      }
      if (s.key === 'saving' && saveNew !== null) {
        const parts = []
        if (saveNew > 0) parts.push(`${n(saveNew)} new`)
        if (saveUpdated > 0) parts.push(`${n(saveUpdated)} updated`)
        if (saveUnchanged > 0) parts.push(`${n(saveUnchanged)} unchanged`)
        if (saveFailed > 0) parts.push(`${n(saveFailed)} failed`)
        if (parts.length) kpi = parts.join(' · ')
      }
    }
    if (status === 'active' && s.key === 'listing' && filesFound > 0) {
      kpi = `${n(filesFound)} files found so far`
    }
    if (status === 'active' && s.key === 'lifecycle') {
      // filesEvaluated live = progress.files_evaluated during "lifecycle" phase ticks
      const liveEval = progress.files_evaluated ?? null
      const liveTotal = progress.files_found ?? null
      const liveRules = progress.rules_enabled ?? null
      if (liveRules !== null && liveRules === 0) {
        kpi = '— No enabled rules'
      } else if (liveEval !== null && liveRules !== null && liveTotal !== null) {
        kpi = `Applying ${n(liveRules)} lifecycle rule${liveRules === 1 ? '' : 's'} · ${n(liveEval)} of ${n(liveTotal)} files evaluated`
      }
    }

    return { ...s, label: displayLabel, status, kpi }
  })

  // After 90 s with no files found during listing, the source likely has many folders to walk.
  const showLongRunningHint = elapsed >= 90 && filesFound === 0 && phase === 'discovering'
  // Lifecycle evaluation can take 30+ s on large inventories.
  const showLifecycleSlowHint = elapsed >= 30 && phase === 'lifecycle'
  // Show a note during reading when any files have been skipped due to exceptions.
  const showReadingExceptions = phase === 'reading' && totalExceptions > 0

  const activeStepKey = steps.find((s) => s.status === 'active')?.key ?? null
  const stopHint = onStop && busy && !stopping && activeStepKey
    ? (STOP_HINTS[activeStepKey] ?? null)
    : null

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
    const matched = lifecycleMatches ?? lifecycleMatchedCount ?? 0
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
          {folderWorkersConfigured !== null && (
            <details style={{ marginBottom: 10, fontSize: 12.5 }}>
              <summary style={{ cursor: 'pointer', color: 'var(--muted)',
                                listStyle: 'none', display: 'flex', alignItems: 'center', gap: 6,
                                userSelect: 'none' }}>
                <span style={{ fontSize: 10 }}>▶</span>
                <span>Technical details</span>
              </summary>
              <div style={{ paddingLeft: 16, paddingTop: 6, color: 'var(--muted)', lineHeight: 1.7 }}>
                <div>Folder traversal concurrency: up to {folderWorkersConfigured}</div>
              </div>
            </details>
          )}
          <div style={{ borderTop: '1px solid var(--line,#e4e8ec)', paddingTop: 12,
                        fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.6 }}>
            <div>{[
              `${n(totalFiles)} files discovered`,
              matched > 0
                ? [
                    `${n(matched)} matched`,
                    lcArchive > 0 && `${n(lcArchive)} Archive Candidate${lcArchive === 1 ? '' : 's'}`,
                    lcDelete > 0 && `${n(lcDelete)} Delete Candidate${lcDelete === 1 ? '' : 's'}`,
                    lcTagged > 0 && `${n(lcTagged)} tagged`,
                  ].filter(Boolean).join(' · ')
                : '0 matched lifecycle rules',
            ].join(' · ')}</div>
            {hasClassStats ? (
              <div>
                {[
                  clsAssessable > 0 && `${n(clsAssessable)} assessable`,
                  clsMetadataOnly > 0 && `${n(clsMetadataOnly)} metadata-only`,
                  clsUnsupported > 0 && `${n(clsUnsupported)} unsupported`,
                  clsEligibilityUnknown > 0 && `${n(clsEligibilityUnknown)} unknown`,
                  clsExcluded > 0 && `${n(clsExcluded)} excluded`,
                ].filter(Boolean).join(' · ')}
              </div>
            ) : assessableCount !== null ? (
              <div>{n(assessableCount)} assessable · {n(unsupportedCount)} not assessable</div>
            ) : null}
            {totalExceptions > 0 && (
              <div>
                {[
                  excInaccessible && `${n(excInaccessible)} inaccessible`,
                  excDeleted && `${n(excDeleted)} deleted during scan`,
                  excMetadataFailure && `${n(excMetadataFailure)} unreadable`,
                ].filter(Boolean).join(' · ')} — skipped during metadata read.
              </div>
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
        <span role="status" aria-live="polite" aria-atomic="true"
              style={{ position: 'absolute', width: 1, height: 1, padding: 0, margin: -1,
                       overflow: 'hidden', clip: 'rect(0,0,0,0)', whiteSpace: 'nowrap',
                       border: 0 }}>
          {activeStepLabel ? `Step in progress: ${activeStepLabel}` : null}
        </span>

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
        {stopHint && (
          <p className="muted" style={{ fontSize: 12.5, margin: '12px 0 0', lineHeight: 1.5 }}>
            {stopHint}
          </p>
        )}
        {showReadingExceptions && (
          <p className="muted" style={{ fontSize: 12.5, margin: '12px 0 0', lineHeight: 1.5 }}>
            {[
              excInaccessible && `${n(excInaccessible)} file${excInaccessible !== 1 ? 's' : ''} inaccessible`,
              excDeleted && `${n(excDeleted)} deleted during scan`,
              excMetadataFailure && `${n(excMetadataFailure)} unreadable`,
            ].filter(Boolean).join(' · ')} — skipped, others continuing.
          </p>
        )}
      </div>

      <p className="muted" style={{ fontSize: 12.5, margin: 0, lineHeight: 1.6 }}>
        Partial inventory will be retained. Source files will not be changed.
      </p>
    </section>
  )
}

import { useState, useEffect, useRef } from 'react'
import WorkerCard from './WorkerCard.jsx'

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

// Phases during which the backend emits `current` (the file being processed).
const FILE_ACTIVE_PHASES = new Set(['reading', 'analysing', 'scoring'])

// How many steps (from the front of STEPS) are DONE at each backend phase.
// Steps: 0=connected, 1=listing, 2=saving, 3=lifecycle
//
// Listing, metadata reading and classification used to be three separate steps here, each with
// its own KPI — but checked directly against the backend (api/handlers.py, scanner.py's _list):
// they are ONE combined operation. The Drive/SharePoint list call already returns metadata, and
// classification runs inline per item as the walk happens; nothing in the backend ever reports
// them as distinct phases (grepped api/handlers.py, core.py, worker.py — 'reading'/'tagging' are
// never set as a live job phase; only 'discovering' and 'lifecycle' are, for the durable path).
// Showing three checkmarks that always flip in the exact same instant was not extra transparency,
// it was the opposite: a screen implying three timed steps for one, found live 2026-08-26 from a
// user report of "no updates, then it suddenly jumps to lifecycle rules." One step that ticks a
// real live file count for its real duration is the honest version of the same information.
//
// 'saving' sits BETWEEN listing and lifecycle, not after lifecycle — that is the real backend
// order (api/handlers.py: add_inventory() persists the listed rows, THEN lifecycle rules
// evaluate against what was just persisted). The step used to be listed last with no live phase
// at all, so it silently flipped done at the same instant as everything else — found live
// 2026-08-26 alongside the missing folder count.
//
// 'reading'/'tagging'/'analysing'/'scoring'/'finalizing' are kept as tolerant aliases below (not
// removed) in case an older backend, a different scan path, or queuedProgress.js's own inferred
// fallback still emits one — never a reason to render fewer done steps than actually happened.
// 'analysing' means "per-file work is underway", which today is always lifecycle rule
// evaluation (the only per-file loop left post-ADR-0020), so it maps to lifecycle's slot (3),
// not saving's (2) — saving is one bulk write with no per-file signal of its own. 'scoring' and
// 'finalizing' meant "further along than that — wrapping up" back when saving was the LAST step
// (see the comment above STEPS): with lifecycle now last, there is no non-terminal slot between
// "lifecycle active" and true completion, so they map past it, to 4 — every step (including
// lifecycle) shows done, nothing pulses, but this is still the in-progress checklist, not the
// `phase === 'done'` completion card (isDone is a separate, exact string check on `phase`, not
// on this table) — an honest "essentially finished, formal completion pending" reading rather
// than leaving lifecycle stuck showing active after its own per-file work is actually done.
// Steps: 0=connected, 1=inventory (listing+classifying+saving), 2=lifecycle, 3=finalizing
//
// Saving is merged into the inventory step because add_inventory() writes batches throughout
// the BFS walk — it is not a distinct sequential phase. Showing it as a separate step implied
// a sequence that does not exist. 'saving' phase now maps to 1 (inventory still active), not 2.
// 'analysing'/'lifecycle' both mean "per-file lifecycle rule evaluation", so they map to 2 (inventory
// done, lifecycle active). 'scoring'/'finalizing' map to 3 (lifecycle done, finalization active).
const PHASE_DONE_COUNT = {
  queued: 0, connecting: 0,
  discovering: 1, reading: 1, tagging: 1, saving: 1,
  analysing: 2, lifecycle: 2,
  scoring: 3, finalizing: 3,
  done: 4,
}

// Each step has a present-tense label (active/pending) and a past-tense label (done).
const STEPS = [
  { key: 'connected',  label: 'Connect to source',        labelDone: 'Connected to source' },
  { key: 'inventory',  label: 'Build document inventory',  labelDone: 'Built document inventory' },
  { key: 'lifecycle',  label: 'Apply lifecycle rules',     labelDone: 'Applied lifecycle rules' },
  { key: 'finalizing', label: 'Finalize Discovery',        labelDone: 'Finalized Discovery' },
]

// Per-step explanation of what stop does while that step is active.
const STOP_HINTS = {
  inventory:  'Stops at the next folder — files found and classified so far will be kept.',
  lifecycle:  'Rules already applied will be kept.',
  finalizing: 'The final inventory write will complete before stopping.',
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

export default function DiscoverRunProgress({ progress, busy, onStop, sources, inv = null, onReview, onContinue, preflightDegraded = null, freshness = null }) {
  const [startedAt] = useState(() => Date.now())
  const [elapsed, setElapsed] = useState(0)
  const [stopping, setStopping] = useState(false)
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
  const lcUnevaluable = progress.unevaluable ?? null
  const evalRate = progress.rate_per_second ?? null
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
      if (s.key === 'inventory' && filesFound > 0) {
        kpi = foldersFound !== null
          ? `${n(filesFound)} files · ${n(foldersFound)} folders`
          : `${n(filesFound)} files found`
      }
      if (s.key === 'lifecycle') {
        if (rulesEnabled !== null) {
          kpi = rulesEnabled === 0
            ? '— No enabled rules'
            : `${n(lifecycleMatches ?? 0)} matched`
        } else if (lifecycleMatchedCount !== null) {
          kpi = lifecycleMatchedCount === 0 ? '— No enabled rules' : `${n(lifecycleMatchedCount)} matched`
        }
      }
      if (s.key === 'finalizing' && saveNew !== null) {
        const total = (saveNew ?? 0) + (saveUpdated ?? 0) + (saveUnchanged ?? 0)
        if (total > 0) kpi = `${n(total)} records saved`
      }
    }
    if (status === 'active' && s.key === 'inventory' && filesFound > 0) {
      kpi = foldersFound !== null
        ? `${n(filesFound)} files · ${n(foldersFound)} folders`
        : `${n(filesFound)} files found`
    }
    if (status === 'active' && s.key === 'lifecycle') {
      const liveEval = progress.files_evaluated ?? null
      const liveTotal = progress.files_found ?? null
      const liveRules = progress.rules_enabled ?? null
      if (liveRules !== null && liveRules === 0) {
        kpi = '— No enabled rules'
      } else if (liveEval !== null && liveTotal !== null) {
        kpi = `${n(liveEval)} of ${n(liveTotal)} evaluated`
      } else if (liveRules !== null) {
        kpi = `${n(liveRules)} rule${liveRules === 1 ? '' : 's'}`
      }
    }

    return { ...s, label: displayLabel, status, kpi }
  })

  // No progress ticks for 90 s — connection may be lost.
  const showStalledWarning = busy && !isDone && stalledSecs >= 90
  // After 90 s with no files found during listing, the source likely has many folders to walk.
  const showLongRunningHint = !showStalledWarning && elapsed >= 90 && filesFound === 0 && phase === 'discovering'
  // Lifecycle evaluation can take 30+ s on large inventories.
  const showLifecycleSlowHint = !showStalledWarning && elapsed >= 30 && phase === 'lifecycle'
  // Show a note during listing when any files have been skipped due to exceptions. Was gated on
  // 'reading', a phase the backend never actually emits live (listing/metadata/classification are
  // one operation — see PHASE_DONE_COUNT's comment) — this notice could not fire for a real scan
  // until now.
  const showReadingExceptions = phase === 'discovering' && totalExceptions > 0

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

  // Retrying card (PRD §16.8) — a transient failure requeued the job with backoff; a worker will
  // reclaim it, but nothing is running right now. Distinct from the stopped/failed card below:
  // `busy` is still true (the scan is not over — see worker.py's on_retry hook, core.py's
  // _job_is_stale phase=='retrying' exemption), so falling through to the ordinary checklist
  // would show step 0 ("Connect to source") as newly active — implying the scan restarted from
  // nothing, when really it is the SAME job, SAME attempt count, waiting on backoff. No countdown
  // to the next attempt is shown: backoff is jittered server-side and a fabricated ETA would be
  // wrong as often as right, the same reasoning that keeps the queued card free of a queue
  // position (see that card's own comment).
  if (busy && phase === 'retrying') {
    const attempt = progress.attempt ?? null
    const maxAttempts = progress.max_attempts ?? null
    const lastError = progress.last_error ?? null
    return (
      <section className="discover-run-progress" role="region" aria-label="Discovery retrying"
               style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 20 }}>
        <div className="assess-run-card" style={{ border: '1px solid var(--line,#e4e8ec)', borderRadius: 12,
                                                  padding: '14px 16px', background: 'var(--panel,#fff)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
            <div style={{ fontSize: 14.5, fontWeight: 650 }}>Discovery retrying</div>
            {onStop && (
              <button type="button" className="ghost small" onClick={handleStop}
                      disabled={stopping}
                      title="Cancel — no attempt is currently running">
                {stopping ? 'Cancelling…' : 'Cancel'}
              </button>
            )}
          </div>
          <div role="status" aria-live="polite" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span className="prep-pulse" aria-hidden="true" />
            <span style={{ fontSize: 13.5 }}>
              A previous attempt failed — waiting to retry
              {attempt !== null && (
                <span className="muted" style={{ marginLeft: 8, fontVariantNumeric: 'tabular-nums' }}>
                  · attempt {attempt}{maxAttempts ? ` of ${maxAttempts}` : ''}
                </span>
              )}
            </span>
          </div>
          {lastError && (
            <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--line,#e4e8ec)',
                          fontSize: 12.5, color: 'var(--muted)' }}>
              {lastError}
            </div>
          )}
        </div>
      </section>
    )
  }

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
              <div>{n(totalFiles)} file{totalFiles !== 1 ? 's' : ''} catalogued.</div>
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

  // DiscoverCompleteSummary takes over once the scan is fully done and not running.
  if (isDone && !busy) return null

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
            {freshness === 'reconnecting' && (
              <span title="Live connection lost — reconnecting. Discovery may still be running." role="status"
                    style={{ fontSize: 11.5, padding: '2px 7px', borderRadius: 4,
                             background: 'var(--amber-bg,#fffbeb)', color: 'var(--amber-ink,#92400e)',
                             border: '1px solid var(--amber,#d97706)' }}>
                reconnecting
              </span>
            )}
            {freshness === 'checkpoint' && (
              <span title="Live connection lost — showing last checkpoint" role="status"
                    style={{ fontSize: 11.5, padding: '2px 7px', borderRadius: 4,
                             background: 'var(--amber-bg,#fffbeb)', color: 'var(--amber-ink,#92400e)',
                             border: '1px solid var(--amber,#d97706)' }}>
                checkpoint
              </span>
            )}
            {freshness === 'stale' && (
              <span title="No live signal and no recent checkpoint — data may be outdated" role="status"
                    style={{ fontSize: 11.5, padding: '2px 7px', borderRadius: 4,
                             background: 'var(--red-bg,#fef2f2)', color: 'var(--red,#b91c1c)',
                             border: '1px solid var(--red-line,#fca5a5)' }}>
                stale
              </span>
            )}
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

        {/* Inventory sub-step expansion — visible only while Building document inventory is active.
            Shows the concurrent sub-operations (listing, classifying, saving) without implying
            they are sequential top-level steps. Each sub-row is conditional on having data. */}
        {phase === 'discovering' && (
          <div style={{ marginTop: 8, paddingLeft: 26, display: 'flex', flexDirection: 'column',
                        gap: 5, fontSize: 12.5, color: 'var(--muted)' }}>
            {(foldersFound !== null || (progress.folder_requests_active ?? null) !== null) && (
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Listing folders</span>
                <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {foldersFound !== null ? `${n(foldersFound)} visited` : null}
                  {(progress.folder_requests_active ?? 0) > 0
                    ? ` · ${n(progress.folder_requests_active)} active` : null}
                </span>
              </div>
            )}
            {filesFound > 0 && (
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Reading metadata</span>
                <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {(progress.metadata_complete ?? null) !== null
                    ? `${n(progress.metadata_complete)} complete`
                    : `${n(filesFound)} found`}
                  {(progress.metadata_incomplete ?? 0) > 0
                    ? ` · ${n(progress.metadata_incomplete)} incomplete` : null}
                </span>
              </div>
            )}
            {clsAssessable !== null && (
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Classifying documents</span>
                <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {n(clsAssessable)} assessable
                  {(clsUnsupported ?? 0) + (clsMetadataOnly ?? 0) > 0
                    ? ` · ${n((clsUnsupported ?? 0) + (clsMetadataOnly ?? 0))} other` : null}
                </span>
              </div>
            )}
            {saveNew !== null && (
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Saving inventory</span>
                <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {n((saveNew ?? 0) + (saveUpdated ?? 0))} saved
                  {(saveFailed ?? 0) > 0 ? ` · ${n(saveFailed)} failed` : null}
                </span>
              </div>
            )}
          </div>
        )}

        {/* Lifecycle progress bar and detail — visible while Apply lifecycle rules is active.
            Uses a determinate <progress> bar because files_found is fixed once inventory is done.
            One bar only; no overall percentage is fabricated. */}
        {phase === 'lifecycle' && filesEvaluated !== null && filesFound > 0 && (
          <div style={{ marginTop: 10, paddingLeft: 26 }}>
            <progress value={filesEvaluated} max={filesFound}
                      aria-label={`Lifecycle evaluation: ${n(filesEvaluated)} of ${n(filesFound)} files`}
                      aria-valuetext={`${n(filesEvaluated)} of ${n(filesFound)} files evaluated`}
                      style={{ width: '100%', height: 5, display: 'block', marginBottom: 6 }} />
            <div style={{ fontSize: 12.5, color: 'var(--muted)', display: 'flex',
                          flexDirection: 'column', gap: 4 }}>
              {lifecycleMatches !== null && lifecycleMatches > 0 && (
                <div>
                  {[
                    `${n(lifecycleMatches)} matched`,
                    lcArchive > 0 && `${n(lcArchive)} Archive Candidate${lcArchive === 1 ? '' : 's'}`,
                    lcDelete > 0 && `${n(lcDelete)} Delete Candidate${lcDelete === 1 ? '' : 's'}`,
                    lcTagged > 0 && `${n(lcTagged)} tagged`,
                  ].filter(Boolean).join(' · ')}
                </div>
              )}
              {(lcUnevaluable ?? 0) > 0 && (
                <div>{n(lcUnevaluable)} could not be evaluated</div>
              )}
              {evalRate !== null && evalRate > 0 && (
                <div style={{ color: 'var(--muted)' }}>{n(evalRate)} files/sec</div>
              )}
            </div>
          </div>
        )}

        {FILE_ACTIVE_PHASES.has(phase) && (filesFound > 0 || progress.current) && (
          <WorkerCard current={progress.current || null}
                      filesDone={progress.files_done ?? 0}
                      filesTotal={filesFound}
                      elapsed={elapsed} />
        )}

        {/* Announces phase transitions to screen readers without repeating per-tick KPI counts.
            Placed after the step list so step label text in the list is found first by indexOf. */}
        <span role="status" aria-live="polite" aria-atomic="true"
              style={{ position: 'absolute', width: 1, height: 1, padding: 0, margin: -1,
                       overflow: 'hidden', clip: 'rect(0,0,0,0)', whiteSpace: 'nowrap',
                       border: 0 }}>
          {activeStepLabel ? `Step in progress: ${activeStepLabel}` : null}
        </span>

        {/* discovery/preflight returned 'degraded' when this scan started (e.g. the durable
            queue was backed up) — allowed through rather than blocked, but worth saying why,
            for as long as this run lasts. Informational, not role="alert": the scan is
            proceeding, this is not a fault. */}
        {preflightDegraded && preflightDegraded.length > 0 && (
          <p className="muted" style={{ fontSize: 12.5, margin: '12px 0 0', lineHeight: 1.5 }}>
            Started with a note: {preflightDegraded.join(' · ')}
          </p>
        )}

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
            {(progress?.files_evaluated > 0 && progress?.files_found > 0)
              ? `Lifecycle evaluation is taking longer than usual — ${n(progress.files_evaluated)} of ${n(progress.files_found)} files evaluated so far.`
              : 'Lifecycle evaluation is taking longer than usual.'}
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

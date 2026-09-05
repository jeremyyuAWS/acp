import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  getRemediationExceptions, retryRemediationDelivery, retryRemediationDocuments,
  cancelRemediationRun, pauseRemediationRun, resumeRemediationRun,
} from './api.js'
import {
  eligibleFiles, groupSummary, outcomeDetails, outcomeMessage, outcomeTone, reconcileSelection,
  visibleItems, OUTCOME_LABELS, VISIBLE_PER_GROUP,
} from './remediationExceptions.js'

// Region E — "does anyone need to act?" (PRD §6E).
//
// SUBORDINATE TO THE NARRATIVE, ON PURPOSE. This sits below the progress account and beside the
// activity feed, at the panel's own smallest type, with no colour-only signalling and no badge
// competing with the headline. PRD §6E asks the panel to "lead with actionable exceptions"; §28's
// version-2 decision is that the run is ONE live narrative. Both hold at once only if the actions
// are legible where the eye already is — the alternative, a red action bar above the counters,
// makes every run look like it is in trouble, including the 148 documents that are going fine.
//
// NOTHING HERE DECIDES ANYTHING. Eligibility, refusal reasons, group membership and which controls
// exist are all read off the server's payload. See remediationExceptions.js for why.

const REFRESH_MS = 4000

export function useRemediationExceptions(runId, revision) {
  const [view, setView] = useState(null)
  const [error, setError] = useState(false)
  const lastFetch = useRef(0)
  const live = useRef(true)

  const load = useCallback(() => {
    if (!runId) return Promise.resolve()
    lastFetch.current = Date.now()
    return getRemediationExceptions(runId)
      .then((next) => { if (live.current) { setView(next); setError(false) } })
      // The last view stays on screen. A transient read failure is not evidence that the
      // exceptions went away, and clearing them would tell the user their run is now clean.
      .catch(() => { if (live.current) setError(true) })
  }, [runId])

  useEffect(() => {
    live.current = true
    setView(null)
    if (!runId) return undefined
    load()
    return () => { live.current = false }
  }, [runId, load])

  useEffect(() => {
    // Follows the snapshot's revision rather than polling on a clock of its own: the run already
    // has one live connection, and a second timer would ask the server the same question twice.
    // Throttled because a busy run bumps its revision every few hundred milliseconds and the
    // exception set does not change nearly that often.
    if (!runId || revision == null) return undefined
    const since = Date.now() - lastFetch.current
    if (since >= REFRESH_MS) { load(); return undefined }
    const timer = setTimeout(load, REFRESH_MS - since)
    return () => clearTimeout(timer)
  }, [runId, revision, load])

  return { view, error, reload: load }
}

function Control({ control, busy, onRun }) {
  return <span className="remops-control">
    <button type="button" className="ghost" disabled={!control.available || busy}
            data-testid={`remops-x-control-${control.action}`}
            aria-describedby={`remops-control-scope-${control.action}`}
            onClick={() => onRun(control.action)}>{control.label}</button>
    <span id={`remops-control-scope-${control.action}`} className="remops-control-scope">
      {control.available ? control.scope : control.reason}
    </span>
  </span>
}

function Item({ item, selected, onToggle }) {
  const id = `remops-x-${item.group}-${item.file}`
  return <li className="remops-x-item">
    <label htmlFor={id}>
      <input id={id} type="checkbox" checked={selected} disabled={!item.action_enabled}
             data-testid={`remops-x-check-${item.file}`}
             onChange={() => onToggle(item.file)} />
      <span className="remops-x-file">{item.file}</span>
    </label>
    {item.review_items > 0 && <span className="remops-x-note">
      {item.review_items} review item{item.review_items === 1 ? '' : 's'}
    </span>}
    {item.destination?.label && item.action_enabled && <span className="remops-x-note">
      → {item.destination.label}
    </span>}
    {/* The refusal, in full, next to the document it is about. A disabled control with the
        reason somewhere else is the thing this region replaces. */}
    {!item.action_enabled && item.action_reason &&
      <span className="remops-x-reason"
            data-testid={`remops-x-reason-${item.file}`}>{item.action_reason}</span>}
  </li>
}

function Group({ group, selection, onToggle, onRun, busy, result }) {
  const [expanded, setExpanded] = useState(false)
  const items = visibleItems(group, expanded)
  const hidden = (group.items || []).length - items.length
  const targets = eligibleFiles(group, { selected: selection, expanded })
  const details = outcomeDetails(result)
  const chosen = targets.length && selection.size ? ` ${targets.length} selected` : ''
  return <section className="remops-x-group" data-testid={`remops-x-group-${group.key}`}
                  aria-labelledby={`remops-x-h-${group.key}`}>
    <h4 id={`remops-x-h-${group.key}`}>{group.label} <span>· {groupSummary(group)}</span></h4>
    <p className="remops-x-summary">{group.summary}</p>
    <ul>{items.map((item) => <Item key={item.file} item={item}
                                   selected={selection.has(item.file)} onToggle={onToggle} />)}</ul>
    {hidden > 0 && <button type="button" className="linklike" aria-expanded={expanded}
                           data-testid={`remops-x-expand-${group.key}`}
                           onClick={() => setExpanded((value) => !value)}>
      {expanded ? 'Show fewer' : `Show ${hidden} more document${hidden === 1 ? '' : 's'}`}
    </button>}
    {group.action && <div className="remops-x-actions">
      <button type="button" disabled={busy || targets.length === 0}
              data-testid={`remops-x-action-${group.key}`}
              onClick={() => onRun(group, targets)}>
        {group.action_label}{chosen || (targets.length ? ` (${targets.length})` : '')}
      </button>
      {/* The one sentence that separates the two retry buttons. A user who reads nothing else
          must still not confuse "re-send the copy we made" with "remediate this again". */}
      <span className="remops-x-scope">{group.reapplies_fixes
        ? 'Re-opens each document and applies approved fixes again.'
        : 'Re-sends the corrected copy that already passed verification. No fix is re-applied.'}</span>
    </div>}
    {details.length > 0 && <ul className="remops-x-outcomes"
                               data-testid={`remops-x-outcomes-${group.key}`}>
      {details.map((row) => <li key={row.file} className={`remops-x-outcome-${outcomeTone(row.outcome)}`}>
        <span className="remops-x-file">{row.file}</span>
        <span>{OUTCOME_LABELS[row.outcome] || row.outcome}{row.message ? ` — ${row.message}` : ''}</span>
      </li>)}
    </ul>}
  </section>
}

// `heading` is the section's own <h3>, and `null` means the caller already named this region —
// the panel wraps it in a Disclosure whose <summary> is that name, and two identical headings one
// above the other is a worse outcome than either. The section keeps an accessible name either way.
export function exceptionCount(view) {
  return (view?.groups || []).reduce((sum, group) => sum + (group.documents || 0), 0)
}

export default function RemediationExceptions({ view, error = false, onReload = null,
                                                runId = null, onAnnounce = null,
                                                heading = 'Needs attention' }) {
  const [selection, setSelection] = useState(() => new Set())
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState({})
  // Reported UP, never announced here. The panel owns the run's one polite live region — see its
  // comment on `announcement` for why a second one is not additive.
  const announce = useCallback((text) => onAnnounce?.(text), [onAnnounce])
  const groups = useMemo(() => view?.groups || [], [view])

  useEffect(() => {
    // Reconciled rather than cleared: a live update that dropped the user's ticks mid-review would
    // lose their place, and one that KEPT a tick on a document the server has since delivered
    // would send a retry for it. Neither is acceptable, so the set is intersected with what is
    // still actionable. Focus is untouched — nothing here moves it (PRD §12).
    setSelection((current) => {
      const next = reconcileSelection(current, groups)
      return next.size === current.size ? current : next
    })
  }, [groups])

  const toggle = useCallback((file) => setSelection((current) => {
    const next = new Set(current)
    if (next.has(file)) next.delete(file); else next.add(file)
    return next
  }), [])

  const runGroup = useCallback((group, files) => {
    if (!runId || !files.length) return
    const call = group.action === 'retry_delivery' ? retryRemediationDelivery
      : retryRemediationDocuments
    setBusy(true)
    call(runId, files)
      .then((result) => {
        setResults((current) => ({ ...current, [group.key]: result }))
        announce(outcomeMessage(result) || '')
        return onReload?.()
      })
      .catch(() => announce('That action could not be sent. Nothing was changed.'))
      .finally(() => setBusy(false))
  }, [runId, onReload, announce])

  const runControl = useCallback((action) => {
    if (!runId) return
    const call = { cancel: cancelRemediationRun, pause: pauseRemediationRun,
                   resume: resumeRemediationRun }[action]
    if (!call) return
    setBusy(true)
    call(runId)
      .then((result) => {
        announce(action === 'pause'
          ? `Run paused. ${result.held ?? 0} document${result.held === 1 ? '' : 's'} held`
            + `${result.in_flight ? `, ${result.in_flight} still finishing` : ''}.`
          : action === 'resume'
            ? `Run resumed. ${result.released ?? 0} document${result.released === 1 ? '' : 's'} released.`
            : `Stopping. ${result.documents_asked_to_stop ?? 0} document`
              + `${result.documents_asked_to_stop === 1 ? '' : 's'} asked to stop; corrected copies are kept.`)
        return onReload?.()
      })
      .catch(() => announce('That action could not be sent. Nothing was changed.'))
      .finally(() => setBusy(false))
  }, [runId, onReload, announce])

  const controls = (view?.controls || []).filter((control) => control.available)
  // THE REGION IS ALWAYS PRESENT, even before its first read lands and even when the run is
  // clean. It occupies a fixed half of the panel's bottom row, so returning null leaves a torn
  // layout — and a heading that appears the moment something goes wrong is a heading nobody has
  // learned where to look for. "Nothing needs a decision or a retry" is also an answer worth
  // giving on a run that is going well.
  return <section className="remops-exceptions"
                  {...(heading ? { 'aria-labelledby': 'remops-x-title' }
                               : { 'aria-label': 'Needs attention' })}>
    {heading && <h3 id="remops-x-title">{heading}{groups.length
      ? ` · ${exceptionCount(view)}` : ''}</h3>}
    {error && <p className="remops-x-stale" role="status">
      ACP could not refresh this list just now. What is shown is the last it confirmed.
    </p>}
    {!view && !error && <p className="muted">Checking for exceptions…</p>}
    {view && groups.length === 0 &&
      <p className="muted">Nothing needs a decision or a retry on this run.</p>}
    {groups.map((group) => <Group key={group.key} group={group} selection={selection}
                                  onToggle={toggle} onRun={runGroup} busy={busy}
                                  result={results[group.key]} />)}
    {controls.length > 0 && <div className="remops-x-controls">
      {controls.map((control) => <Control key={control.action} control={control} busy={busy}
                                          onRun={runControl} />)}
    </div>}
  </section>
}

export { VISIBLE_PER_GROUP }

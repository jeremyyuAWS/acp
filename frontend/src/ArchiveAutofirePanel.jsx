import { useCallback, useEffect, useRef, useState } from 'react'
import { getArchiveCandidates, runArchiveAutofire } from './api.js'
import { prefersReducedMotion } from './a11y.js'
import {
  ARCHIVED, BLOCKED, ELIGIBLE_AUTO, RECOMMEND_ONLY, RECOVERY_REQUIRED, TOUCHED,
  evidenceLabel, refusalText, runProgress, stateSpec, transitionMessage,
} from './archiveAutofire.js'

// Discovery results — the archive auto-fire lane for one scan, and the live activity of a run.
//
// WHAT THIS SURFACE IS FOR. Discovery already lists lifecycle candidates; what it could not say
// was WHICH of them a machine is about to move and on what grounds. Every row here carries its
// state, its reason, and — behind a disclosure — the actual evidence, because "inspect the
// supersession evidence before execution" is only real if the evidence is in the surface where
// the decision is visible, not in an audit log somebody would have to go and find.
//
// NO STATE IS CARRIED BY COLOR. Each row leads with a text mark and the full state name
// (archiveAutofire.STATES), so the five states are distinguishable in a screenshot, in high
// contrast, and to a reader who does not perceive the difference. This page is about
// irreversible actions; "the red one" is not a distinction anybody should rely on.
//
// FOCUS RETURNS TO THE ROW. Opening a row's evidence and closing it again puts focus back on the
// disclosure that opened it — otherwise a keyboard user is dropped at the top of the document
// after every inspection, which on a list of forty candidates means re-traversing the list forty
// times.
//
// POLLING RESPECTS REDUCED MOTION by not existing under it: the auto-refresh is replaced by an
// explicit Refresh button. That is WCAG 2.2.2's actual requirement rather than a decorative
// reading of it — a list that reorders itself under someone is the moving content, and a spinner
// is not the point. The live region is polite and only announces MEANINGFUL transitions
// (`transitionMessage` returns '' for a repeat), so a poll that changed nothing is silent and no
// timer tick is ever announced.

const line = '1px solid var(--line)'
const ORDER = [RECOVERY_REQUIRED, BLOCKED, ELIGIBLE_AUTO, ARCHIVED, RECOMMEND_ONLY]

export default function ArchiveAutofirePanel({ scanId }) {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [announcement, setAnnouncement] = useState('')
  const [open, setOpen] = useState(null)
  const lastSeen = useRef({})
  const triggers = useRef({})

  const refresh = useCallback(() => {
    if (!scanId) return Promise.resolve()
    return Promise.resolve().then(() => getArchiveCandidates(scanId))
      .then((value) => {
        setReport(value)
        setError('')
        // Announce only what CHANGED, and only for a document whose state actually moved.
        const messages = []
        for (const item of value.items || []) {
          const message = transitionMessage(lastSeen.current[item.file], item)
          if (message) messages.push(message)
          lastSeen.current[item.file] = { state: item.state, file: item.file }
        }
        if (messages.length) setAnnouncement(messages.slice(0, 3).join(' '))
      })
      .catch(() => setError('The archive lane for this scan could not be loaded. '
                          + 'Lifecycle recommendations below are unaffected.'))
  }, [scanId])

  useEffect(() => { refresh() }, [refresh])

  useEffect(() => {
    if (prefersReducedMotion() || !scanId) return undefined
    const timer = window.setInterval(refresh, 15000)
    return () => window.clearInterval(timer)
  }, [refresh, scanId])

  const start = () => {
    setBusy(true); setError('')
    Promise.resolve().then(() => runArchiveAutofire(scanId))
      .then(() => refresh())
      .catch((e) => setError(refusalText(e)))
      .finally(() => setBusy(false))
  }

  if (!scanId) return null
  if (!report) {
    return <section className="panel" aria-label="Automatic archive lane">
      {error ? <p role="alert">{error}</p> : <p className="muted">Loading the archive lane…</p>}
    </section>
  }

  const items = [...(report.items || [])].sort(
    (a, b) => ORDER.indexOf(a.state) - ORDER.indexOf(b.state)
      || String(a.file).localeCompare(String(b.file)))
  const counts = report.counts || {}
  const eligible = Number(counts.eligible || 0)

  return <section className="panel" aria-labelledby="archive-lane-heading">
    <h2 id="archive-lane-heading">Archive lifecycle run</h2>

    {/* The counts line, stated in the same words the server states them in
        (archive_autofire.run_progress) — measured only, no percentage, no estimate. */}
    <p style={{ fontWeight: 600 }}>{runProgress(counts)}</p>

    {report.dry_run && <p role="status">
      <b>Dry run.</b> Every safety check runs against the real source system and no file is moved.
    </p>}

    {/* Polite, and quiet by construction: transitionMessage returns '' for an unchanged state, so
        a poll that found nothing new announces nothing. Timer ticks are never announced because
        nothing produces a message for one. */}
    <p role="status" aria-live="polite" className="sronly">{announcement}</p>

    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', margin: '10px 0' }}>
      <button type="button" onClick={start} disabled={busy || !eligible}>
        {busy ? 'Running…' : `Archive ${eligible.toLocaleString()} eligible file${eligible === 1 ? '' : 's'}`}
      </button>
      <button type="button" onClick={refresh} disabled={busy}>Refresh</button>
    </div>
    {!eligible && <p className="muted" style={{ fontSize: 12.5 }}>
      Nothing in this scan is eligible for automatic archival. Every candidate below is a
      recommendation for a person to decide.
    </p>}

    {error && <p role="alert">{error}</p>}

    <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
      {items.map((item) => {
        const spec = stateSpec(item.state)
        const isOpen = open === item.file
        return <li key={item.file} style={{ borderTop: line, padding: '10px 0' }}>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'baseline' }}>
            {/* The mark is decorative ONLY in the sense that the label repeats it in words —
                aria-hidden so a screen reader is not read a punctuation character before every
                state name it is about to hear anyway. */}
            <span aria-hidden="true" style={{ fontWeight: 700 }}>{spec.mark}</span>
            <b>{spec.label}</b>
            <span style={{ overflowWrap: 'anywhere' }}>{item.file}</span>
            {TOUCHED.has(item.state) && <span className="muted" style={{ fontSize: 12 }}>
              — this file was acted on
            </span>}
          </div>
          <p className="muted" style={{ fontSize: 12.5, margin: '4px 0 0', lineHeight: 1.5 }}>
            {item.reason || spec.help}
          </p>
          <button type="button"
                  ref={(el) => { triggers.current[item.file] = el }}
                  aria-expanded={isOpen}
                  onClick={() => {
                    const next = isOpen ? null : item.file
                    setOpen(next)
                    // Closing returns focus to the control that opened it, so a keyboard user on a
                    // long list is not dropped back at the top after every inspection.
                    if (next === null) triggers.current[item.file]?.focus()
                  }}
                  style={{ marginTop: 6 }}>
            {isOpen ? 'Hide the evidence' : 'Show the evidence'}
          </button>
          {isOpen && <div style={{ marginTop: 8, paddingLeft: 12, borderLeft: line }}>
            <p style={{ fontSize: 12.5, margin: 0 }}>{item.evidence_summary}</p>
            {!!(item.evidence || []).length && <ul style={{ fontSize: 12.5, lineHeight: 1.55 }}>
              {item.evidence.map((e, i) => <li key={i}>
                <b>{evidenceLabel(e.type)}</b><br />
                {e.detail}<br />
                <span className="muted">
                  This document {e.source_item_id} · replacement {e.replacement_item_id}
                  {e.replacement_path ? ` (${e.replacement_path})` : ''}
                </span>
              </li>)}
            </ul>}
            {!!(item.rejected_evidence || []).length && <>
              <p style={{ fontSize: 12.5, margin: '8px 0 2px' }}><b>Not accepted as evidence</b></p>
              <ul style={{ fontSize: 12.5, lineHeight: 1.55 }}>
                {item.rejected_evidence.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </>}
            <dl style={{ display: 'grid', gridTemplateColumns: 'minmax(90px,140px) 1fr', gap: 6,
                         fontSize: 12.5, margin: '8px 0 0', overflowWrap: 'anywhere' }}>
              <dt>Source path</dt><dd style={{ margin: 0 }}>{item.path || 'Not recorded'}</dd>
              <dt>Would move to</dt>
              <dd style={{ margin: 0 }}>{item.destination_path || 'No destination resolved'}</dd>
              <dt>Source</dt>
              <dd style={{ margin: 0 }}>{item.source_connection || 'Not recorded'}</dd>
            </dl>
          </div>}
        </li>
      })}
    </ul>

    {!items.length && <p>No archive candidates were recorded for this scan.</p>}

    <p className="muted" style={{ fontSize: 12.5 }}>
      Age never authorizes an automatic move. A file is archived automatically only where a newer
      document is proven to supersede it and the tenant policy permits it.
    </p>
  </section>
}

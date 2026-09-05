import { useEffect, useRef, useState } from 'react'
import { getDocumentTimeline } from './api.js'
import { auditTrail, auditSummary, stamp } from './documentAudit.js'

// R10 · Audit trail — the record of what was changed on one document, by whom or by what, and when.
//
// This renders `store.document_timeline`, which is assembled from persisted rows and infers nothing.
// The three columns the design asks for are not equally well supported, and the component is built
// around that inequality rather than around the design:
//
//   WHEN     fully supported. Every event carries its own `ts` from the table it came from.
//   WHAT     supported for what was WRITTEN, not for what it replaced. `applied_fixes` stores the
//            value a fix wrote and no prior value, so the trail can say "alt text set to X" and
//            cannot say what X displaced. Before → after is a different endpoint
//            (`remediation-diffs`), persisted only for fixes that verifiably cleared, and this
//            component does not pretend to carry it.
//   BY WHOM  supported on three of the eight event kinds, and on those three it is nullable. See
//            documentAudit.js. Rows whose actor the record does not hold are attributed to the
//            automation that produced them — which is derivable from the kind and is true — and are
//            marked as derived, so a reader can see which attributions the log actually made.
//
// AN EMPTY TRAIL IS NOT PROOF, and this one has a specific reason to say so. `api.getDocumentTimeline`
// now REJECTS on a transport failure instead of resolving to `[]`, so this component can tell a
// failed read from a document with no history and says which it is — the `err` branch below. That
// distinction did not exist when this file was written; the empty state's wording still matters
// because one case survives it: in the SIM build the call returns `[]` unconditionally, so an empty
// trail there is a property of the build and not of the document. The empty state therefore keeps
// saying what it does and does not establish rather than reading as "nothing has happened".

const kicker = { fontSize: 11.5, letterSpacing: '.07em', textTransform: 'uppercase',
                 color: 'var(--muted)', fontWeight: 600 }
const muted = { fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }

// Kinds are marked, not coloured by severity — an audit trail has no good and bad events. The two
// that CHANGED the document are the only ones given weight, because "what was changed" is the
// question this screen exists to answer and the rest is context around it.
const KIND_LABEL = {
  scan: 'scan', ai: 'AI call', review: 'queued for review', human: 'human decision',
  fix: 'change', publish: 'published', decision: 'decision', certify: 'certified',
}

function Row({ r }) {
  const [copied, setCopied] = useState(false)
  const copyCorrelation = async () => {
    if (!r.correlationId || !navigator.clipboard?.writeText) return
    await navigator.clipboard.writeText(r.correlationId)
    setCopied(true)
  }
  return (
    <li className="audit-row" data-kind={r.kind} data-changed={r.changed ? '1' : '0'}
        style={{ display: 'grid', gridTemplateColumns: 'minmax(140px, auto) 1fr',
                 gap: 12, padding: '9px 0', borderTop: '1px solid var(--line)' }}>
      <div>
        <div className="audit-when" style={{ fontSize: 11.5, fontVariantNumeric: 'tabular-nums',
                                             color: 'var(--muted)', whiteSpace: 'nowrap' }}>{stamp(r.ts)}</div>
        <div style={{
          display: 'inline-block', marginTop: 3, fontSize: 10.5, fontWeight: 700,
          letterSpacing: '.03em', textTransform: 'uppercase', borderRadius: 5, padding: '1px 6px',
          color: r.changed ? '#1F4D22' : 'var(--muted)',
          background: r.changed ? '#E4F2E2' : 'transparent',
          border: r.changed ? '1px solid #C6E2C2' : '1px solid var(--line)',
        }}>{KIND_LABEL[r.kind] || r.kind}</div>
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, wordBreak: 'break-word' }}>
          {r.title}
          {r.ruleId && <span className="muted" style={{ fontWeight: 400, fontSize: 11.5 }}> · WCAG {r.ruleId}</span>}
        </div>
        {r.detail && <div style={{ ...muted, marginTop: 2, wordBreak: 'break-word' }}>{r.detail}</div>}
        <div className="audit-by" style={{ ...muted, marginTop: 2 }}>
          by <b style={{ fontWeight: 600 }}>{r.by}</b>
          {/* The distinction the whole module turns on: whether the log named this actor, or whether
              the component read it off the kind of event. Both are true; they are not equally strong,
              and an audit reader is exactly the person who needs to know which one they are looking at. */}
          {r.attribution === 'derived'
            ? <span className="audit-derived"> — the record names no actor for this event; this is
                read from what kind of event it is</span>
            : <span className="audit-recorded"> — recorded in the log</span>}
        </div>
        {r.correlationId && (
          <button type="button" className="linklike audit-copy-correlation" onClick={copyCorrelation}
                  aria-label={`Copy correlation ID ${r.correlationId}`}>
            {copied ? 'Copied correlation ID' : 'Copy correlation ID'}
          </button>
        )}
      </div>
    </li>
  )
}

/**
 * @param scanId       the scan. Without it nothing is fetched and nothing renders.
 * @param file         the document.
 * @param changesOnly  start with the trail filtered to events that changed the document. The toggle
 *                     is always offered; the other six kinds are context, not noise, and hiding them
 *                     permanently would make the trail unable to answer "why was this changed".
 */
export default function DocumentAudit({ scanId, file, changesOnly = false }) {
  const [events, setEvents] = useState(null)      // null = not loaded
  const [err, setErr] = useState('')
  const [onlyChanges, setOnlyChanges] = useState(changesOnly)
  const onRef = useRef(true)

  useEffect(() => {
    onRef.current = true
    setEvents(null)
    if (!scanId || !file) return undefined
    getDocumentTimeline(scanId, file)
      .then((d) => { if (onRef.current) { setEvents(Array.isArray(d) ? d : []); setErr('') } })
      .catch((e) => { if (onRef.current) setErr(e?.message || 'unavailable') })
    return () => { onRef.current = false }
  }, [scanId, file])

  if (!scanId || !file) return null

  const rows = auditTrail(events)
  // Before the fetch answers, state that it is loading. This avoids presenting a false empty trail
  // while giving slow connections an honest, screen-reader-visible progress state.
  if (!rows) {
    return err
      ? <details className="panel documentaudit" aria-label="Audit trail" style={{ marginBottom: 14 }}>
          <summary style={{ cursor: 'pointer', padding: 14, fontWeight: 700 }}>Audit trail · unavailable</summary>
          <div style={{ padding: '0 14px 14px' }}>
            <p style={{ ...muted, margin: 0 }}>The trail for this document could not be loaded: {err}.</p>
          </div>
        </details>
      : <div className="panel documentaudit documentaudit-loading" role="status" aria-live="polite">Loading audit trail…</div>
  }

  const s = auditSummary(rows)
  const shown = onlyChanges ? rows.filter((r) => r.changed) : rows
  const exportAudit = () => {
    const blob = new Blob([JSON.stringify({ scanId, file, exportedAt: new Date().toISOString(), events: rows }, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${String(file).replace(/[^a-z0-9._-]+/gi, '-')}-audit.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <details className="panel documentaudit" aria-label="Audit trail" style={{ marginBottom: 14 }}>
      <summary style={{ cursor: 'pointer', padding: 14, display: 'flex', gap: 10,
        alignItems: 'baseline', justifyContent: 'space-between', listStylePosition: 'inside' }}>
        <span><b>Audit trail</b> <span className="muted" style={{ fontSize: 12 }}>· {file}</span></span>
        <span className="muted" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
          {s.events} {s.events === 1 ? 'event' : 'events'} · {s.changes} {s.changes === 1 ? 'change' : 'changes'}
        </span>
      </summary>
      <div className="documentaudit-body" style={{ padding: '0 14px 14px', borderTop: '1px solid var(--line)' }}>
      <div style={{ ...kicker, marginTop: 12 }}>Recorded history</div>
      <h2 style={{ margin: '4px 0 0', fontSize: 18, wordBreak: 'break-word' }}>{file}</h2>

      {rows.length === 0 ? (
        <p className="audit-empty" style={{ ...muted, marginTop: 8 }}>
          No events are recorded for this document in this scan. That is what the trail returned — it
          is not evidence that nothing happened: the client returns an empty list for a failed request
          as well as for an empty history, and the demo build has no ledger to read at all.
        </p>
      ) : (
        <>
          <p className="audit-summary" style={{ fontSize: 13, lineHeight: 1.55, marginTop: 8, marginBottom: 0 }}>
            <b style={{ fontVariantNumeric: 'tabular-nums' }}>{s.events}</b>{' '}
            {s.events === 1 ? 'event' : 'events'}, of which{' '}
            <b style={{ fontVariantNumeric: 'tabular-nums' }}>{s.changes}</b>{' '}
            changed the document.{' '}
            {s.people > 0
              ? <>The log names {s.people === 1 ? 'one person' : `${s.people} people`}: {s.peopleNames.join(', ')}.</>
              : <>The log names no person on any of these events.</>}
          </p>
          <p style={{ ...muted, marginTop: 4 }}>
            The trail records the value each change wrote. It does not record what that value replaced
            — before-and-after evidence is kept separately, and only for fixes a re-scan confirmed.
          </p>

          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 8, fontSize: 12.5 }}>
            <input type="checkbox" checked={onlyChanges} onChange={(e) => setOnlyChanges(e.target.checked)} />
            Changes only
          </label>
          <button type="button" className="ghost small audit-export" onClick={exportAudit} style={{ marginLeft: 10 }}>
            Export audit record
          </button>

          {shown.length === 0 ? (
            <p className="audit-nochanges" style={{ ...muted, marginTop: 8 }}>
              Nothing in this trail changed the document. Every event here read it, drafted against it,
              or recorded a decision about it.
            </p>
          ) : (
            <ul style={{ listStyle: 'none', margin: '8px 0 0', padding: 0 }}>
              {shown.map((r, i) => <Row key={`${r.ts}-${r.kind}-${i}`} r={r} />)}
            </ul>
          )}
        </>
      )}
      </div>
    </details>
  )
}

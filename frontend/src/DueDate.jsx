import { useEffect, useRef, useState } from 'react'
import { saveDecision } from './api.js'

// R19 · Due date — the deadline half of "who does this, by when". It pairs with the R17 assignee
// axis: a due date rides the same per-file scan_decisions store (kind='due_date'), owner-scoped, one
// per document. The design's own caution is built in: "a due date with no owner is a decoration",
// so when a date is set on a document nobody owns, this says so rather than pretending the deadline
// will reach anyone.
//
// Scoped to the document (the selected finding's file), like the assignee it complements — not to a
// single finding. It persists directly through the decision API, so it stays self-contained and does
// not thread state through the inbox.

const kicker = { fontSize: 11.5, letterSpacing: '.07em', textTransform: 'uppercase',
                 color: 'var(--muted)', fontWeight: 600 }
const muted = { fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }

const day = (s) => (s ? String(s).slice(0, 10) : '')          // ISO date/timestamp -> YYYY-MM-DD

/**
 * @param scanId    the scan the document belongs to.
 * @param file      the document (the selected finding's file).
 * @param value     the persisted due date for this file (ISO date/timestamp), or '' if none.
 * @param assignee  the document's current assignee email, so an ownerless deadline can say so.
 * @param now       injectable clock (ms) for deterministic overdue tests; defaults to Date.now().
 */
export default function DueDate({ scanId, file, value = '', assignee = '', now = Date.now() }) {
  const [date, setDate] = useState(day(value))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const live = useRef(true)

  // Re-seed when the selected document (or its persisted value) changes — the component is reused
  // across selections, so stale local state would show one document's deadline on another.
  useEffect(() => { setDate(day(value)); setErr('') }, [file, value])
  useEffect(() => () => { live.current = false }, [])

  if (!scanId || !file) return null

  const persist = (next) => {
    setBusy(true); setErr('')
    // value=null deletes the decision (clears the date); a date string upserts it.
    saveDecision(scanId, file, 'due_date', next || null)
      .then(() => { if (live.current) setDate(next) })
      .catch((e) => { if (live.current) setErr(e?.message || 'could not save the due date') })
      .finally(() => { if (live.current) setBusy(false) })
  }

  const todayStr = day(new Date(now).toISOString())
  const overdue = !!date && date < todayStr

  return (
    <section className="panel due-date" role="region" aria-label="Due date for this document"
             style={{ marginBottom: 14 }}>
      <div style={kicker}>Due date</div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 6, flexWrap: 'wrap' }}>
        <input type="date" value={date} disabled={busy} aria-label="Due date"
               onChange={(e) => persist(e.target.value)}
               style={{ fontSize: 13, padding: '6px 9px', border: '1px solid var(--line)',
                        borderRadius: 8, fontFamily: 'inherit' }} />
        {date && (
          <button type="button" onClick={() => persist('')} disabled={busy}
                  style={{ fontSize: 12.5, padding: '6px 11px', borderRadius: 8,
                           border: '1px solid var(--line)', cursor: busy ? 'default' : 'pointer' }}>
            Clear
          </button>
        )}
        {overdue && (
          <span className="due-overdue" style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.03em',
                  textTransform: 'uppercase', color: '#7f1d1d', background: '#fbe6e6',
                  border: '1px solid #f0c9c9', borderRadius: 5, padding: '2px 7px' }}>
            Overdue
          </span>
        )}
      </div>

      {date && !assignee && (
        <p className="due-noowner" style={{ ...muted, marginTop: 8 }}>
          No owner yet — a due date with no one assigned is a decoration. Assign this document so the
          deadline has someone to reach.
        </p>
      )}
      {!date && (
        <p style={{ ...muted, marginTop: 8 }}>No due date set for this document.</p>
      )}
      {err && <p style={{ ...muted, marginTop: 8, color: 'var(--red, #b23b3b)' }}>{err}</p>}
    </section>
  )
}

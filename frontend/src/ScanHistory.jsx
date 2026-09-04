import { useEffect, useState } from 'react'
import { getScanHistory } from './api.js'
import { normalizeHistory } from './scanHistory.js'
import { stamp } from './documentAudit.js'

// ADR 0042 · Run history — what happened to THIS RUN, from the durable event log.
//
// The run-level sibling of DocumentAudit (which answers the same question about one document), and
// it exists because until ADR 0042 there was no answer at all. Live progress is a mutable cell in
// Redis with a one-hour TTL: reconnect after it expires, or after an Azure revision rollout moved
// the replica, and the run reads as "scan interrupted" with nothing to say how far it got. These
// rows are ordinary Postgres and outlive all of that.
//
// COLLAPSED BY DEFAULT, and deliberately so. This is operator diagnostics, and it sits in
// RunDetails for the same reason scan traces do — one more click for the engineer, off the page
// entirely for everyone else. It is opened by the person asking "why did this take twenty
// minutes", not read routinely.
//
// FETCHED ON EXPAND, not on mount. A collapsed panel that nobody opens should not cost a request
// on every render of the run-details screen; the cost belongs to the click that wants the answer.
//
// AN EMPTY HISTORY IS NOT PROOF, and the two ways of being empty are different sentences:
//   · the request FAILED — getScanHistory rejects on a transport error (it never resolves to an
//     empty list to mean that), so `err` says the history could not be read.
//   · the run has NO EVENTS — genuinely possible and worth stating plainly, because runs that
//     predate ADR 0042 have none and never will. Saying "nothing happened" about those would be
//     false; saying "no recorded history" is true.

const kicker = { fontSize: 11.5, letterSpacing: '.07em', textTransform: 'uppercase',
                 color: 'var(--muted)', fontWeight: 600 }
const muted = { fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }

const SEVERITY_STYLE = {
  bad: { color: '#7A1F1F', background: '#F7E4E4', border: '1px solid #E7C4C4' },
  warn: { color: '#7A5B10', background: '#FBF1DC', border: '1px solid #EBDCB4' },
  ok: { color: 'var(--muted)', background: 'transparent', border: '1px solid var(--line)' },
}

function Row({ e }) {
  return (
    <li className="run-history-row" data-kind={e.kind} data-severity={e.severity}
        style={{ display: 'grid', gridTemplateColumns: 'minmax(150px, auto) 1fr',
                 gap: 12, padding: '9px 0', borderTop: '1px solid var(--line)' }}>
      <div>
        <div className="run-history-when"
             style={{ fontSize: 11.5, fontVariantNumeric: 'tabular-nums',
                      color: 'var(--muted)', whiteSpace: 'nowrap' }}>{stamp(e.at)}</div>
        <div style={{ display: 'inline-block', marginTop: 3, fontSize: 10.5, fontWeight: 700,
                      letterSpacing: '.03em', textTransform: 'uppercase', borderRadius: 5,
                      padding: '1px 6px', ...SEVERITY_STYLE[e.severity] }}>{e.label}</div>
      </div>
      <div style={{ minWidth: 0 }}>
        {e.fields.length > 0 && (
          <div style={{ fontSize: 13, wordBreak: 'break-word' }}>
            {e.fields.map((f, i) => (
              <span key={f.label}>
                {i > 0 && <span className="muted"> · </span>}
                <span className="muted">{f.label} </span>
                <b style={{ fontWeight: 600 }}>{f.value}</b>
              </span>
            ))}
          </div>
        )}
        <div className="run-history-meta" style={{ ...muted, marginTop: 2 }}>
          {/* Only what distinguishes this row from the ordinary case: attempt is withheld when it
              is 1, and worker/job ids are shown because "which worker" is the question a reclaimed
              run raises. See scanHistory.js. */}
          {e.attempt && <span>attempt <b style={{ fontWeight: 600 }}>{e.attempt}</b> · </span>}
          {e.workerId && <span>worker <code>{e.workerId}</code> · </span>}
          {e.jobId && <span>job <code>{e.jobId}</code></span>}
        </div>
      </div>
    </li>
  )
}

export default function ScanHistory({ scanId }) {
  const [open, setOpen] = useState(false)
  const [model, setModel] = useState(null)
  const [err, setErr] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open || !scanId) return
    let live = true
    setLoading(true); setErr(null)
    getScanHistory(scanId)
      .then((raw) => { if (live) setModel(normalizeHistory(raw)) })
      .catch(() => { if (live) setErr('could not be read') })
      .finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [open, scanId])

  // Re-collapsing and re-opening refetches rather than showing a cached list: the run may still be
  // in flight, and a stale list under a "history" heading is the one thing this panel must not be.
  useEffect(() => { if (!open) setModel(null) }, [open])

  if (!scanId) return null

  return (
    <section className="run-history" style={{ marginTop: 18 }}>
      <button type="button" onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              style={{ ...kicker, background: 'none', border: 'none', padding: 0,
                       cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
        <span aria-hidden="true">{open ? '▾' : '▸'}</span> Run history
      </button>
      <p style={{ ...muted, margin: '4px 0 0' }}>
        The recorded lifecycle of this run — when it was queued, which worker took it, and what it
        did. Kept in the database, so it survives a restart or a deploy that ends the live view.
      </p>

      {open && loading && (
        <p className="run-history-loading" role="status" aria-live="polite"
           style={{ ...muted, marginTop: 8 }}>Loading run history…</p>
      )}

      {open && err && (
        <p className="run-history-error" role="alert" style={{ ...muted, marginTop: 8 }}>
          This run’s history {err}. That is a problem reaching the server, not a statement about
          the run — it does not mean nothing happened.
        </p>
      )}

      {open && !loading && !err && model && !model.available && (
        <p className="run-history-empty" style={{ ...muted, marginTop: 8 }}>
          No history is recorded for this run.
        </p>
      )}

      {open && !loading && !err && model?.available && model.events.length === 0 && (
        <p className="run-history-empty" style={{ ...muted, marginTop: 8 }}>
          No lifecycle events were recorded for this run. Runs from before this was introduced have
          none, and will not gain any — this is not a statement that nothing happened.
        </p>
      )}

      {open && !loading && !err && model?.available && model.events.length > 0 && (
        <>
          {(model.retries > 0 || model.workers.length > 1) && (
            <p className="run-history-summary" style={{ ...muted, marginTop: 8 }}>
              {model.retries > 0 && <>Retried <b style={{ fontWeight: 600 }}>{model.retries}</b>{' '}
                {model.retries === 1 ? 'time' : 'times'}. </>}
              {model.workers.length > 1 && (
                <>Handled by <b style={{ fontWeight: 600 }}>{model.workers.length}</b> workers — the
                  run was reclaimed after its first worker stopped reporting.</>
              )}
            </p>
          )}
          <ul style={{ listStyle: 'none', margin: '8px 0 0', padding: 0 }}>
            {model.events.map((e) => <Row key={e.seq ?? `${e.kind}-${e.at}`} e={e} />)}
          </ul>
        </>
      )}
    </section>
  )
}

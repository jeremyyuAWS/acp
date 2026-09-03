import { useEffect, useRef, useState } from 'react'
import { listScanDecisions, remediateScan } from './api.js'
import { subscribeJobs } from './jobsFeed.js'
import { outcomeFor, OUTCOMES, autoLaneSize } from './fixOutcome.js'

// R8 · If a fix fails — what a person sees, and can do, when remediation of a document does not
// end in a corrected copy.
//
// The lane this grows out of is `FailureLane.jsx`, which reads the same `/jobs` feed and answers the
// OPERATIONAL question: which jobs are being retried, which have dead-lettered. That is one of the
// states here and it is imported rather than re-derived (`fixOutcome.js` calls FailureLane's own
// `classifyFailure`). What this screen adds is the other three: a run that declined, a fix that was
// written and did not clear, and a document nothing has been attempted on. Those never reach the job
// queue at all — a run that refuses a document completes successfully — so a failure lane alone
// cannot see them, and a screen built only on it reports them as nothing at all.
//
// TWO PROHIBITIONS, both of which this component would otherwise break naturally:
//
//   · Before both feeds have answered, this renders NOTHING. Not "0 failures". `outcomeFor` returns
//     null while `loaded` is false and the section returns null with it, because an empty failure
//     list is a strong claim ("everything worked") and it must not be made by a screen that has not
//     read anything yet.
//   · A retry is offered only where re-running the originating action is real. `remediate_file` has
//     no server-side requeue — the backend's own guidance is to re-run the originating action — so
//     the button calls `remediateScan(scanId, [file])`, and it is offered ONLY for a terminal
//     dead-letter. A run that refused the document will refuse it again, and a button promising
//     otherwise is a lie with a spinner on it.
//
// WHAT A SUCCESSFUL REMEDIATION ACTUALLY WROTE, because the reassuring answer is the wrong one.
// ADR 0010 makes Azure Blob the primary store; the Drive write is a mirror, and
// `store.get_drive_mirror_enabled()` defaults to TRUE — so on a default deployment a remediated copy
// IS written into a "Remediated" folder in the customer's own drive. This screen therefore never
// says "nothing was written to your drive". Where the mirror failed and Blob did not, it says the
// fix succeeded and the Drive copy did not, which is what the record shows.

const card = { border: '1px solid var(--line)', borderRadius: 12, background: 'var(--surface)' }
const kicker = { fontSize: 11.5, letterSpacing: '.07em', textTransform: 'uppercase',
                 color: 'var(--muted)', fontWeight: 600 }
const muted = { fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }

// Tone separates the states that mean something BROKE from the states that mean the system worked
// and produced no change. Colouring all six would make that distinction disappear.
const TONE = {
  failed: 'var(--error-fg-strong)', unreadable: 'var(--error-fg-strong)', unverified: '#8A4B0B',
  refused: 'var(--muted)', applied: '#2F7D32', not_attempted: 'var(--muted)',
}

// What to do next, per state. Absent for the states whose honest next step is "nothing here".
const NEXT_STEP = {
  failed: 'Fix the cause, then retry the remediation for this document.',
  unreadable: 'Re-run the scan for this document — remediation has nothing to work from until it is assessed.',
  unverified: 'The criteria that did not clear stayed failing and are waiting in the review queue.',
  refused: 'Nothing to retry. Whatever this document still needs is a person’s to do.',
}

function OutcomeRow({ r, autoLane, onRetry, retried, busy }) {
  return (
    <div className="fixoutcome-row" data-outcome={r.outcome}
         style={{ ...card, marginTop: 10, padding: '10px 12px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 260px', minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 700, wordBreak: 'break-word' }}>{r.file}</div>
          <div className="fixoutcome-state" style={{ fontSize: 12.5, fontWeight: 600, marginTop: 2,
                       color: TONE[r.outcome] || 'var(--muted)' }}>{r.label}</div>
          <div style={{ ...muted, marginTop: 2 }}>{r.meaning}</div>
        </div>
        <div style={{ flex: '0 0 auto', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 5 }}>
          {r.job && r.job.kind !== 'in_flight' && (
            <span style={{ fontSize: 11.5, fontWeight: 600, color: TONE.failed, whiteSpace: 'nowrap' }}>
              {r.job.kind === 'dead' ? '✕ dead-letter' : '↻ retrying'}
              {r.job.maxAttempts ? ` · ${r.job.attempts}/${r.job.maxAttempts} attempts` : ''}
            </span>
          )}
          {r.retryable && (retried
            ? <span style={{ fontSize: 11.5, color: 'var(--success-fg)', whiteSpace: 'nowrap' }}>✓ re-queued</span>
            : <button className="ghost small" disabled={busy} onClick={() => onRetry(r)}
                      title="Re-run the remediation for this one document as a new job">↻ Retry this document</button>)}
        </div>
      </div>

      {/* The recorded reason, verbatim. Where nothing was recorded, SAY so rather than filling the
          gap — a guess dressed as a finding is what sent a whole investigation to the wrong place. */}
      {r.reason
        ? <div className="fixoutcome-reason" style={{
            fontSize: 12, marginTop: 6, color: r.reasonSource === 'job' ? '#8A2A20' : 'var(--fg)',
            fontFamily: r.reasonSource === 'job' ? 'ui-monospace, monospace' : 'inherit',
            wordBreak: 'break-word',
          }}>{r.reason}</div>
        : <div className="fixoutcome-reason" style={{ ...muted, marginTop: 6 }}>
            No reason was recorded for this document in this scan.
          </div>}
      {r.detail && <div style={{ ...muted, marginTop: 2 }}>{r.detail}</div>}

      {/* A refusal is legible only next to what there was to do. `autoLaneSize` counts the findings
          in the deterministic lane; when it is zero, a run declining is the system working. Null
          when the document's findings were not passed in — then this says nothing. */}
      {r.outcome === 'refused' && autoLane === 0 && (
        <div className="fixoutcome-autolane" style={{ ...muted, marginTop: 4 }}>
          Nothing on this document was in the automatic lane, so a run had nothing it could apply.
        </div>
      )}

      {NEXT_STEP[r.outcome] && (
        <div style={{ ...muted, marginTop: 4 }}>{NEXT_STEP[r.outcome]}</div>
      )}

      {/* ADR 0010 — Blob is the must-succeed write, Drive is the mirror. A failed mirror over a
          successful fix is a copy that is missing from a folder, not a fix that did not happen. */}
      {r.mirrorFailed && (
        <div className="fixoutcome-mirror" style={{ ...muted, marginTop: 4 }}>
          The copy in your drive’s “Remediated” folder failed to write
          {r.mirrorDetail ? ` — ${r.mirrorDetail}` : ''}. The corrected copy itself was stored and can
          be downloaded; only the drive mirror is missing.
        </div>
      )}
    </div>
  )
}

/**
 * @param scanId    the scan these documents belong to. Job rows are matched on it, so another scan's
 *                  dead-letter is not reported here.
 * @param files     the scan's file rows (or plain filenames). Absent renders nothing.
 * @param cap       remediation-capability map, used only to say how big the automatic lane was on a
 *                  refused document. Omit and that sentence is simply not shown.
 * @param show      which states to list. Defaults to the four that are not "it worked" — this is the
 *                  failure surface, and `applied` rows belong on the verification screen.
 */
export default function FixOutcomes({ scanId, files, cap = null,
                                      show = ['failed', 'unreadable', 'unverified', 'refused'] }) {
  const [decisions, setDecisions] = useState(null)   // null = not loaded
  const [jobs, setJobs] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [retried, setRetried] = useState({})
  const onRef = useRef(true)

  useEffect(() => {
    onRef.current = true
    if (!scanId) return undefined
    // Two independent reads that used to share one timer: the decisions list is per-scan and
    // stays a private poll, while /jobs rides the shared subscription every other consumer uses.
    const load = () => listScanDecisions(scanId)
      .then((d) => { if (onRef.current) { setDecisions(d || []); setErr('') } })
      .catch((e) => { if (onRef.current) setErr(e?.message || 'unavailable') })
    load()
    const t = setInterval(load, 6000)
    const stop = subscribeJobs(null, (j) => { setJobs(j?.jobs || []) },
                               { intervalMs: 6000,
                                 onError: (e) => setErr(e?.message || 'unavailable') })
    return () => { onRef.current = false; clearInterval(t); stop() }
  }, [scanId])

  const retry = (r) => {
    if (busy || !scanId) return
    setBusy(true)
    Promise.resolve(remediateScan(scanId, [r.file]))
      .then(() => setRetried((m) => ({ ...m, [r.file]: true })))
      .catch((e) => setErr(e?.message || 'retry could not be queued — try again'))
      .finally(() => setBusy(false))
  }

  // Nothing until both feeds have answered. An empty failure list is a claim, and this screen has
  // not earned it yet.
  const loaded = decisions !== null && jobs !== null
  if (!Array.isArray(files) || !scanId) return null
  if (!loaded) {
    return err
      ? <section className="panel fixoutcomes" role="region" aria-label="Remediation outcomes">
          <div style={kicker}>Remediation outcomes</div>
          <p style={{ ...muted, marginTop: 6 }}>Outcome status unavailable: {err}. Nothing below is a
            statement about whether the fixes worked.</p>
        </section>
      : null
  }

  const rows = files
      .map((f) => (typeof f === 'string' ? { file: f } : f))
      .map((f) => ({ f, r: outcomeFor(f.file || f.name, { scanId, decisions, jobs, loaded: true }) }))
      .filter((x) => x.r && show.includes(x.r.outcome))
  // Worst first, in the module's own precedence, so the two states that mean something broke are at
  // the top and the two that mean the system worked are below them.
  rows.sort((a, b) => OUTCOMES.indexOf(a.r.outcome) - OUTCOMES.indexOf(b.r.outcome)
                   || String(a.r.file).localeCompare(String(b.r.file)))

  return (
    <section className="panel fixoutcomes" role="region" aria-label="Remediation outcomes"
             style={{ marginBottom: 14 }}>
      <div style={kicker}>Remediation outcomes</div>
      <h2 style={{ margin: '4px 0 0', fontSize: 18 }}>Documents with no corrected copy</h2>

      {rows.length === 0 ? (
        <p style={{ ...muted, marginTop: 8 }}>
          Every document in this run either has a corrected copy or has no remediation record at all.
          No job failed, and no run declined a document.
        </p>
      ) : (
        <p style={{ fontSize: 13, lineHeight: 1.55, marginTop: 8, marginBottom: 0 }}>
          {rows.length} {rows.length === 1 ? 'document' : 'documents'} came out of remediation without a
          corrected copy, for {new Set(rows.map((x) => x.r.outcome)).size === 1 ? 'one reason' : 'different reasons'}.
          A failed run, a run that declined, and a document nothing was tried on are three different
          situations — each row says which one it is.
        </p>
      )}

      {err && <p style={{ ...muted, marginTop: 6, color: '#8A2A20' }}>Feed error: {err}</p>}

      {rows.map(({ f, r }) => (
        <OutcomeRow key={r.file} r={r} autoLane={autoLaneSize(f, cap)}
                    onRetry={retry} retried={!!retried[r.file]} busy={busy} />
      ))}
    </section>
  )
}

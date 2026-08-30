import { useEffect, useRef, useState } from 'react'
import { clearDeadJobs, remediateScan, rescoreFile } from './api.js'
import { subscribeJobs } from './jobsFeed.js'

// W7 · Operational-failure lane. Until now the flow had the "unsupported type" branch but not
// the "job *failed*" branch — a corrupt file, an OAuth token that expired mid-scan, a source
// gone unreachable, a worker that threw. The durable `jobs` table already backs the retry story
// (queued → running → done, transient failures requeued with backoff until max_attempts, then
// dead-lettered), but nothing on the always-on Monitor surface SHOWED it. Failures were invisible.
//
// This lane reads the same owner-scoped /jobs feed QueuePanel does and surfaces the two things a
// person watching actually needs: what is being RETRIED right now (transient — failed at least
// once, attempts climbing, still short of max), and what has DIED (terminal — retries exhausted).
// Retry re-runs the originating action (there is no server-side requeue endpoint — the backend's
// own guidance is "re-run the originating action to retry", see /admin/jobs/clear-dead); the
// terminal state is the queue's real 'dead' status, cleared via the existing purge.

// Job-type → short human label. Mirrors QueuePanel.JOBLABEL so the two surfaces read the same.
const JOBLABEL = {
  scan_discover: 'discover', scan_file: 'scan file', scan_batch: 'scan batch',
  scan_finalize: 'finalize', remediate_file: 'remediate', assess_trace: 'assess', scan: 'scan',
}

// Which failed job types can be re-driven from the client, and how. There is no generic
// requeue API, so a retry means re-triggering the ORIGINATING action over the same file:
//   - a failed per-file scan  → rescoreFile (re-download + re-score that one document)
//   - a failed per-file remediate → remediateScan scoped to that one file
// Scan-level jobs (discover / batch / finalize / whole-scan / assess) have no single-file
// re-trigger — retrying them means re-running the scan from Discover or the assessment from
// Assess, which this lane points to rather than fakes with a button that can't deliver it.
const RETRYABLE = {
  scan_file: (scanId, file) => rescoreFile(scanId, file),
  rescore_file: (scanId, file) => rescoreFile(scanId, file),
  remediate_file: (scanId, file) => remediateScan(scanId, [file]),
}

const parsePayload = (p) => { try { return JSON.parse(p || '{}') } catch { return {} } }
const jobFile = (jb) => parsePayload(jb.payload).file || null

// A human description of what failed — the document by name when the job is per-file,
// otherwise the phase, so a scan-level failure still reads as more than an opaque id.
const jobDesc = (jb) => {
  const f = jobFile(jb)
  if (f) return f
  switch (jb.type) {
    case 'scan_discover': return 'Finding documents to scan'
    case 'scan_batch': return 'Scanning a batch of documents'
    case 'scan_finalize': return 'Scoring & finalizing results'
    case 'assess_trace': return 'Assessing WCAG coverage'
    case 'scan': return 'Scanning documents'
    default: return jb.scan_id ? `scan ${String(jb.scan_id).slice(0, 8)}` : String(jb.id).slice(0, 8)
  }
}

// Turn a raw last_error into something a person can act on. The backend stores up to 2000
// chars of the exception; the common operational cases get a plain-language lead, and the
// raw text is kept below (and in the title) so nothing is hidden.
const reasonHint = (err) => {
  const e = String(err || '')
  if (/drive token|oauth|401|unauthor|expired|invalid_grant/i.test(e)) return 'The source sign-in expired mid-job. Sign in again, then retry.'
  if (/403|forbidden|permission|access denied/i.test(e)) return 'The source refused access to this file. Check sharing/permissions, then retry.'
  if (/404|not found|no such file|removed/i.test(e)) return 'The file was not found at the source — it may have been moved or deleted.'
  if (/timeout|timed out|unreachable|connection|network|ECONN/i.test(e)) return 'The source was unreachable. It may be a transient outage — retry.'
  if (/corrupt|password|encrypted|cannot parse|unsupported|bad|malformed/i.test(e)) return 'The file could not be opened (corrupt, password-protected, or malformed).'
  return ''
}

// Categorise one job for the lane. Terminal dead-letters are 'dead'; a job that has failed at
// least once but is still within its retry budget (transient) is 'retrying'. A bare 'failed'
// status (some paths surface it before the sweeper decides) is treated as retrying unless its
// attempts have been exhausted. Everything else is not a failure and never reaches the lane.
export function classifyFailure(jb) {
  if (!jb) return null
  const attempts = jb.attempts || 0
  const max = jb.max_attempts || 0
  if (jb.status === 'dead') return 'dead'
  if (jb.status === 'failed') return (max && attempts >= max) ? 'dead' : 'retrying'
  // A queued/running job that already carries an error and more than one attempt is mid-retry.
  if ((jb.status === 'queued' || jb.status === 'running') && jb.last_error && attempts > 1) return 'retrying'
  return null
}

// Split a jobs list into the two lane buckets. Exported for a direct unit test of the
// categorisation, independent of the React rendering.
export function splitFailures(jobs = []) {
  const dead = [], retrying = []
  for (const jb of jobs) {
    const c = classifyFailure(jb)
    if (c === 'dead') dead.push(jb)
    else if (c === 'retrying') retrying.push(jb)
  }
  return { dead, retrying }
}

function FailRow({ jb, kind, onRetry, retried }) {
  const file = jobFile(jb)
  const scanId = jb.scan_id
  const canRetry = kind === 'dead' && !!RETRYABLE[jb.type] && !!scanId && !!file
  const hint = reasonHint(jb.last_error)
  const attempts = jb.attempts || 0
  const max = jb.max_attempts || 0
  return (
    <div className="faillane-row" style={{
      display: 'flex', alignItems: 'flex-start', gap: 10, padding: '9px 0',
      borderTop: '1px solid #F0DADA',
    }}>
      <span style={{
        flex: '0 0 auto', fontSize: 10.5, fontWeight: 700, letterSpacing: '.03em',
        textTransform: 'uppercase', color: '#7A2020', background: '#F7DCDC',
        borderRadius: 5, padding: '2px 7px', marginTop: 1, whiteSpace: 'nowrap',
      }}>{JOBLABEL[jb.type] || jb.type}</span>
      <div style={{ flex: '1 1 auto', minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#3D3A34', wordBreak: 'break-word' }}>{jobDesc(jb)}</div>
        {hint && <div style={{ fontSize: 12.5, color: '#7A4A0B', marginTop: 2 }}>{hint}</div>}
        {jb.last_error && (
          <div title={jb.last_error} style={{
            fontSize: 11.5, fontFamily: 'ui-monospace, monospace', color: '#8A2A20',
            opacity: 0.85, marginTop: 2, wordBreak: 'break-word',
          }}>{jb.last_error.slice(0, 160)}</div>
        )}
      </div>
      <div style={{ flex: '0 0 auto', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 5 }}>
        {kind === 'retrying'
          ? <span style={{ fontSize: 11.5, fontWeight: 600, color: '#854F0B', whiteSpace: 'nowrap' }}>
              ↻ retrying{max ? ` · attempt ${attempts} of ${max}` : attempts ? ` · attempt ${attempts}` : ''}
            </span>
          : <span style={{ fontSize: 11.5, fontWeight: 600, color: '#A32D2D', whiteSpace: 'nowrap' }}>
              ✕ dead-letter{max ? ` · ${attempts}/${max} attempts` : ''}
            </span>}
        {canRetry && (
          retried
            ? <span style={{ fontSize: 11.5, color: '#3B6D11', whiteSpace: 'nowrap' }}>✓ re-queued</span>
            : <button className="ghost small" onClick={() => onRetry(jb)}
                title={`Re-run the ${JOBLABEL[jb.type] || jb.type} for this file as a new job`}>
                ↻ Retry
              </button>
        )}
      </div>
    </div>
  )
}

// The lane. Owner-scoped feed (no run prop needed) — a failure on any of the caller's scans is
// theirs to see. Polls on the same cadence as the queue so a job flipping to dead surfaces here
// within seconds. Renders a quiet "all healthy" line when there is nothing failing, so the lane
// is always-on and honestly reports the good state rather than vanishing.
export default function FailureLane() {
  const [jobs, setJobs] = useState(null)     // null = not loaded yet
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [retried, setRetried] = useState({}) // job id → true once its retry was accepted
  const onRef = useRef(true)

  useEffect(() => {
    onRef.current = true
    // Shared subscription (jobsFeed.js) — this wants the same unfiltered /jobs response
    // QueuePanel, Discover and AssessRunner want.
    const stop = subscribeJobs(null, (d) => { setJobs(d?.jobs || []); setErr('') },
                               { intervalMs: 4000,
                                 onError: (e) => setErr(e?.message || 'unavailable') })
    return () => { onRef.current = false; stop() }
  }, [])

  const retry = (jb) => {
    const run = RETRYABLE[jb.type]
    const file = jobFile(jb)
    if (!run || !jb.scan_id || !file || busy) return
    setBusy(true); setNote('')
    Promise.resolve(run(jb.scan_id, file))
      .then(() => {
        setRetried((m) => ({ ...m, [jb.id]: true }))
        setNote(`↻ Re-queued ${file} — watch it in the Async job queue on the Remediate tab.`)
        return load()
      })
      .catch((e) => setErr(e?.message || 'retry could not be queued — try again'))
      .finally(() => { setBusy(false); setTimeout(() => setNote(''), 6000) })
  }

  const clearDead = () => {
    setBusy(true); setNote('')
    clearDeadJobs()
      .then((d) => { setNote(`✓ cleared ${d?.purged ?? 0} dead-letter job${(d?.purged ?? 0) !== 1 ? 's' : ''}`); return load() })
      .catch((e) => setErr(e?.message || 'could not clear dead-letters'))
      .finally(() => { setBusy(false); setTimeout(() => setNote(''), 4000) })
  }

  // Before the first poll returns, say nothing — an empty lane on load must not read as
  // "all healthy" before we actually know.
  if (jobs === null && !err) return null

  const { dead, retrying } = splitFailures(jobs || [])
  const totalFailing = dead.length + retrying.length

  return (
    <section className="panel faillane" style={{ marginBottom: 14 }}
             aria-label="Operational failures" role="region">
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>
          Operational failures{' '}
          <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>· jobs that failed to run — retry &amp; dead-letter</span>
        </h2>
        {totalFailing > 0 && (
          <span role="status" style={{
            fontSize: 12, fontWeight: 700, color: '#7A2020', background: '#FCEBEB',
            border: '1px solid #F3C9C9', borderRadius: 8, padding: '2px 10px',
          }}>⚠ {totalFailing} need{totalFailing === 1 ? 's' : ''} attention</span>
        )}
      </div>

      {err && !jobs && (
        <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>Failure status unavailable: {err}</p>
      )}

      {jobs && totalFailing === 0 && !err && (
        <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>
          <span style={{ color: '#1a7f37', fontWeight: 600 }}>✓ No operational failures</span>{' '}
          — every scan, assessment and remediation job completed or is in flight. A corrupt file,
          an expired source sign-in, or an unreachable source would appear here with a retry.
        </p>
      )}

      {note && <p style={{ marginTop: 8, fontSize: 12.5, color: '#185FA5' }} role="status">{note}</p>}

      {retrying.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div className="muted" style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.04em' }}>
            Retrying <span style={{ fontWeight: 400, textTransform: 'none' }}>· failed once, being retried automatically with backoff</span>
          </div>
          <div style={{ marginTop: 2 }}>
            {retrying.map((jb) => <FailRow key={jb.id} jb={jb} kind="retrying" onRetry={retry} retried={!!retried[jb.id]} />)}
          </div>
        </div>
      )}

      {dead.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <div className="muted" style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.04em', color: '#A32D2D' }}>
              Dead-letter <span style={{ fontWeight: 400, textTransform: 'none', color: 'var(--muted)' }}>· retries exhausted — fix the cause, then retry, or clear</span>
            </div>
            <button className="ghost small" onClick={clearDead} disabled={busy}
                    title="Remove these terminal-failure jobs from the queue (does not retry the work)">
              Clear dead-letters
            </button>
          </div>
          <div style={{ marginTop: 2 }}>
            {dead.map((jb) => <FailRow key={jb.id} jb={jb} kind="dead" onRetry={retry} retried={!!retried[jb.id]} />)}
          </div>
        </div>
      )}
    </section>
  )
}

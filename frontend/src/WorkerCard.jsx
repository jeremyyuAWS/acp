// Per-scan activity card rendered during reading / analysing / scoring phases.
// The backend emits a single `current` string (the file the worker pool is writing results for)
// alongside aggregate counts. True per-thread cards would require scanner.py changes to emit
// a workers[] array; this card represents the overall pool throughput until that data exists.
//
// Props:
//   current    — the file path currently being processed (may be null / empty)
//   filesDone  — files processed so far
//   filesTotal — total files found (used for the progress bar denominator)
//   elapsed    — wall-clock seconds THE RUN has been going, derived from the server's own
//                started_at (DiscoverRunProgress). null when the server has no timestamp for it,
//                which suppresses the rate and the ETA — both are quotients of this, so a wrong
//                denominator does not produce a slightly-off number, it produces a confident
//                impossible one.

function truncatePath(path, maxLen = 54) {
  if (!path || path.length <= maxLen) return path || ''
  const slash = path.lastIndexOf('/')
  if (slash < 0) return '…' + path.slice(-(maxLen - 1))
  const file = path.slice(slash + 1)
  const dir = path.slice(0, slash)
  if (file.length + 5 <= maxLen) {
    const keep = maxLen - file.length - 5
    return dir.slice(0, Math.max(0, keep)) + '/…/' + file
  }
  return '…/' + file.slice(-(maxLen - 3))
}

function fmtEta(secs) {
  if (secs < 60) return `~${secs}s`
  return `~${Math.ceil(secs / 60)}m`
}

function fmtSpeed(fps) {
  return fps >= 10 ? `${Math.round(fps)} files/s` : `${fps.toFixed(1)} files/s`
}

export default function WorkerCard({ current, filesDone = 0, filesTotal = 0, elapsed = null }) {
  const hasCurrent = !!current
  const pct = filesTotal > 0 ? Math.min(100, (filesDone / filesTotal) * 100) : null
  const speed = elapsed != null && elapsed >= 3 && filesDone > 0 ? filesDone / elapsed : null
  const remaining = filesTotal > filesDone ? filesTotal - filesDone : 0
  const eta = speed && remaining > 0 ? Math.ceil(remaining / speed) : null

  if (!hasCurrent && filesDone === 0) return null

  const label = `${filesDone.toLocaleString()} of ${filesTotal.toLocaleString()} files`

  return (
    <div role="status" aria-label="Processing activity"
         style={{ marginTop: 12, padding: '10px 12px', borderRadius: 8,
                  background: 'var(--surface,#f7f8fa)', border: '1px solid var(--line,#e4e8ec)',
                  fontSize: 12.5 }}>
      {pct !== null && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
          <div role="progressbar"
               aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}
               aria-label={label}
               style={{ flex: 1, height: 4, borderRadius: 2,
                        background: 'var(--line,#e4e8ec)', overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${pct}%`, borderRadius: 2,
                          background: 'var(--accent,#1a7f45)',
                          transition: 'width 0.3s ease' }} />
          </div>
          <span className="muted"
                style={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums',
                         minWidth: 34, textAlign: 'right' }}>
            {Math.round(pct)}%
          </span>
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8,
                    color: 'var(--muted)', lineHeight: 1.5, flexWrap: 'wrap' }}>
        <span style={{ fontVariantNumeric: 'tabular-nums' }}>{label}</span>
        {(speed || eta) && (
          <span style={{ display: 'flex', gap: 10 }}>
            {speed && <span>{fmtSpeed(speed)}</span>}
            {eta && <span aria-label={`estimated ${fmtEta(eta)} remaining`}>{fmtEta(eta)} remaining</span>}
          </span>
        )}
      </div>

      {hasCurrent && (
        <div className="muted"
             style={{ marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap', fontFamily: 'monospace', fontSize: 11.5 }}
             title={current}>
          {truncatePath(current)}
        </div>
      )}
    </div>
  )
}

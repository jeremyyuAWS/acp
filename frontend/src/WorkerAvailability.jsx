// "How many workers are available to pick up scan jobs" — the same worker-count/alive signal
// AssessRunner's worker strip already surfaces from GET /jobs, extracted so Discover can show it
// too without duplicating the polling+adjust wiring, and so Remediate can be a third adopter
// later without a rewrite (same reuse story as ProcessingStatusPanel, #922-#924). Each caller
// keeps its own polling effect and adjustWorkers() — this component is purely presentational.
//
// `snap.workers` is the CONFIGURED pool size (Discover.jsx's adjustWorkers moves it 0..16), not a
// live busy/idle gauge — there is no "N busy" signal in this data to show instead. So "online" +
// "0 workers available to pick up jobs" isn't a transient busy state, it's the service reporting
// it is reachable while explicitly configured to run nothing — and worded as two separate facts
// it read as a contradiction. Said as one fact ("processing capacity is off") instead.
export default function WorkerAvailability({ snap, busy, msg, onAdjust }) {
  if (!snap) return null
  const externallyManaged = snap.runtime_mode === 'distributed' && snap.alive
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '6px 0 10px',
                  fontSize: 12.5, flexWrap: 'wrap' }}>
      <span style={{ color: snap.alive ? '#1a7f37' : '#854F0B', fontWeight: 600 }}>
        ● Worker service&nbsp;<span style={{ fontWeight: 400 }}>{snap.alive ? 'online' : 'offline'}</span>
      </span>
      <span className="muted">·</span>
      <span className="muted">
        {snap.workers === 0
          ? 'Processing capacity is off — no worker will pick up new jobs'
          : `${snap.workers} worker${snap.workers === 1 ? '' : 's'} available to pick up jobs`}
      </span>
      {externallyManaged ? (
        <span className="muted" style={{ marginLeft: 4, fontStyle: 'italic' }}>
          Worker capacity is managed by your deployment administrator.
        </span>
      ) : onAdjust && (
        <span style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 4 }}>
          <span className="muted" style={{ fontSize: 11 }}>Worker concurrency:</span>
          <button onClick={() => onAdjust(-1)} disabled={busy || snap.workers <= 0}
                  aria-label="Remove a worker"
                  style={{ width: 20, height: 20, borderRadius: 5, border: '1px solid var(--line)',
                           background: '#fff', color: 'var(--ink)', fontSize: 14, lineHeight: 1,
                           cursor: 'pointer', display: 'inline-flex', alignItems: 'center',
                           justifyContent: 'center', padding: 0 }}>−</button>
          <span style={{ fontSize: 13, fontWeight: 600, minWidth: 18, textAlign: 'center' }}>{snap.workers}</span>
          <button onClick={() => onAdjust(1)} disabled={busy || snap.workers >= 16}
                  aria-label="Add a worker"
                  style={{ width: 20, height: 20, borderRadius: 5, border: '1px solid var(--line)',
                           background: '#fff', color: 'var(--ink)', fontSize: 14, lineHeight: 1,
                           cursor: 'pointer', display: 'inline-flex', alignItems: 'center',
                           justifyContent: 'center', padding: 0 }}>+</button>
          {msg && <span style={{ fontSize: 11, color: msg.startsWith('Failed') ? '#8A2A20' : '#1a7f37',
                                  fontWeight: 600, marginLeft: 2 }}>{msg}</span>}
        </span>
      )}
    </div>
  )
}

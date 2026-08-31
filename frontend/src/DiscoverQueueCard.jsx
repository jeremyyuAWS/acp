import { fmtPickupRange } from './pickupEstimateFmt.js'

// The consolidated "DISCOVERY · Queued" card (stakeholder UX review, 2026-08-30) — replaces the
// three separate, sometimes-contradicting pieces Discover used to show for this one window
// (queue facts inside ProcessingStatusPanel, worker/Azure info in a separate WorkerAvailability
// strip, and a plain-text placeholder) with one card answering, in order, the three questions a
// queued scan actually raises: is this really queued (not stuck), what capacity exists to pick
// it up, and when. Purely presentational — every field is independently optional, and a caller
// that cannot supply one omits it rather than rendering a placeholder or a fabricated zero,
// matching ProcessingStatusPanel's and WorkerAvailability's own existing rule for this.
//
// Deliberately scoped to ONLY the pre-claim "waiting" window. Once a worker claims the job,
// Discover falls back to its existing "Worker assigned" / actively-discovering UI (which already
// has its own live counts, folder activity, etc.) — this card would have nothing left to add
// there, and duplicating a second progress readout beside the real one is exactly the
// contradiction this exists to remove.
function fmtAgo(secs) {
  if (secs == null || !Number.isFinite(secs)) return null
  const s = Math.max(0, Math.round(secs))
  return s < 60 ? `${s}s ago` : `${Math.round(s / 60)}m ago`
}

const row = (label, value) => (value == null ? null : (
  <div key={label} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 13 }}>
    <span className="muted">{label}</span>
    <span style={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
  </div>
))

export default function DiscoverQueueCard({
  compatibleJobsAhead = null, workersTotal = null, workersOnline = null,
  submittedSecsAgo = null, queueUpdatedSecsAgo = null,
  pickupEstimate = null, capacity = null, replicas = null,
  onStop = null, onViewMonitor = null,
}) {
  const pickupRange = pickupEstimate?.state === 'estimated' && pickupEstimate.earliest_at && pickupEstimate.latest_at
    ? fmtPickupRange(pickupEstimate.earliest_at, pickupEstimate.latest_at) : null
  const noWorker = pickupEstimate?.state === 'no_worker_available'
    || (workersTotal === 0 && !workersOnline)
  const provisioning = capacity?.configured && capacity.revision_provisioning_state === 'Provisioning'
  const capacityMeasuredAgo = capacity?.configured && capacity.measured_at
    ? fmtAgo((Date.now() - Date.parse(capacity.measured_at)) / 1000) : null

  const queueRows = [
    row('Compatible jobs ahead', compatibleJobsAhead != null ? compatibleJobsAhead : null),
    row('Submitted', fmtAgo(submittedSecsAgo)),
  ].filter(Boolean)

  const capacityRows = [
    replicas?.configured && replicas.min_replicas != null
      ? row('Azure requested', `${replicas.min_replicas} replica${replicas.min_replicas === 1 ? '' : 's'}`) : null,
    capacity?.configured && capacity.current_replicas != null
      ? row('Azure running', `${capacity.current_replicas} replica${capacity.current_replicas === 1 ? '' : 's'}`) : null,
    workersTotal != null
      ? row('ACP ready', workersOnline ? `${workersTotal} worker${workersTotal === 1 ? '' : 's'}` : 'offline') : null,
    capacity?.configured && capacity.draining_replicas
      ? row('Draining', `${capacity.draining_replicas} replica${capacity.draining_replicas === 1 ? '' : 's'} from an older revision`) : null,
  ].filter(Boolean)

  return (
    <div role="status" aria-label="Discovery queue status"
         style={{ background: 'var(--surface, #EEF4FB)', border: '1px solid var(--line, #B7D3EE)',
                  borderRadius: 8, padding: '14px 18px', margin: '8px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
        <span style={{ fontSize: 11, letterSpacing: '.08em', textTransform: 'uppercase', fontWeight: 700, color: 'var(--accent, #1B4C7A)' }}>
          Discovery
        </span>
        <span style={{ fontSize: 12, fontWeight: 600, color: noWorker ? '#8A2A20' : '#1B4C7A' }}>
          {noWorker ? 'No capacity' : 'Queued'}
        </span>
      </div>

      <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 2 }}>
        {noWorker ? 'No compatible worker is currently ready' : 'Waiting for a worker'}
      </div>
      <div style={{ fontSize: 13, color: 'var(--ink-2, #48505C)', marginBottom: 10 }}>
        {noWorker
          ? 'Your request is queued, but no worker is online to pick it up yet.'
          : 'Your request is safely stored and will start automatically.'}
      </div>

      {Number.isFinite(submittedSecsAgo) && submittedSecsAgo >= 30 && (
        <div role="alert" style={{ marginTop: 10, color: 'var(--ink-2, #48505C)' }}>
          Discovery has been queued for more than 30 seconds. Check Monitor for worker
          availability and job details. You can cancel this request; do not submit a duplicate.
        </div>
      )}

      {provisioning && (
        <div style={{ fontSize: 12.5, marginBottom: 10, padding: '6px 10px', borderRadius: 6,
                       background: 'var(--surface-2, #F6EEDF)', color: '#854F0B' }}>
          Azure is provisioning additional capacity — workers usually become ready in under a minute.
        </div>
      )}

      {queueRows.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 10.5, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--ink-3, #6E7784)', marginBottom: 4 }}>
            Queue
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>{queueRows}</div>
        </div>
      )}

      {capacityRows.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 10.5, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--ink-3, #6E7784)', marginBottom: 4 }}>
            Worker capacity
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>{capacityRows}</div>
        </div>
      )}

      <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 3 }}>
        {pickupRange
          ? row('Estimated pickup', pickupRange)
          : (!noWorker && (
              <div style={{ fontSize: 11.5, fontStyle: 'italic', color: 'var(--ink-3, #6E7784)' }}>
                Pickup estimate is still being calculated. ACP needs more recent history before it can provide a reliable range.
              </div>
            ))}
        {queueUpdatedSecsAgo != null && (
          <div style={{ fontSize: 11, color: 'var(--ink-3, #6E7784)' }}>Queue updated {fmtAgo(queueUpdatedSecsAgo)}</div>
        )}
        {capacityMeasuredAgo && (
          <div style={{ fontSize: 11, color: 'var(--ink-3, #6E7784)' }}>Azure capacity measured {capacityMeasuredAgo}</div>
        )}
      </div>

      <div style={{ marginTop: 10, fontSize: 12.5, color: 'var(--ink-2, #48505C)' }}>
        Next: A worker will connect to the source and begin discovering documents.
      </div>

      <div style={{ marginTop: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        {onStop
          ? <button type="button" className="ghost small" onClick={onStop}>Cancel</button>
          : <span />}
        {onViewMonitor && (
          <button onClick={onViewMonitor} className="linklike" style={{ fontSize: 12.5 }}>
            View in Monitor →
          </button>
        )}
      </div>
    </div>
  )
}

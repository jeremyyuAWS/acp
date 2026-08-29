import { isQueueStalled, queuedAgeSecs } from './workerStallSignal.js'
import { diagnoseWorkerHealth } from './workerDiagnosis.js'

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
//
// `snap.oldestQueuedCreatedAt`/`isQueueStalled` (workerStallSignal.js): "online" is a heartbeat,
// not proof anything is actually being claimed — see that module's docstring for the two live
// bugs (#935/#936) that produced exactly this gap on 2026-08-29, both invisible from `alive`
// alone. This is what makes the SAME gap visible next time, whatever causes it.
//
// `replicas` (GET /control/workers/replicas — Azure Container App min/max warm replicas):
// visible to EVERY signed-in user when externally managed, not just admins — this is the
// "how many can pick up jobs" question every caller already sees a coarser version of via
// `snap`, and reading it costs nothing. Only the +/- adjust controls are admin-gated, via
// the PRESENCE of `onAdjustReplicas` (Discover.jsx only passes it for `me?.is_admin`) —
// mirrors exactly how the in-process `onAdjust` controls below are gated by prop presence,
// not by a role check inside this (deliberately dumb, presentational) component.
//
// `capacity` (GET /control/workers/capacity): a SEPARATE question from `replicas` above —
// that's the CONFIGURED warm floor/ceiling; this is what Azure has actually provisioned right
// now and how loaded it is. Read-only for everyone, same as `replicas`, no adjust action at
// all. Individual fields can be null even when capacity.configured is true (the backend
// degrades per-field on a partial Azure/Monitor failure) — rendered as omitted, never as a
// fabricated 0, matching this component's existing "processing capacity is off" vs "0 workers"
// distinction above.
export default function WorkerAvailability({ snap, busy, msg, onAdjust,
                                              replicas, replicasBusy, replicasMsg, onAdjustReplicas,
                                              capacity }) {
  if (!snap) return null
  const externallyManaged = snap.runtime_mode === 'distributed' && snap.alive
  const stalled = isQueueStalled(snap.alive, snap.oldestQueuedCreatedAt)
  const stalledAge = stalled ? queuedAgeSecs(snap.oldestQueuedCreatedAt) : null
  // diagnoseWorkerHealth (workerDiagnosis.js) covers strictly more ground than the stall check
  // above (offline reasons, revision health, capacity ceiling) but its own queue-stall rule
  // would otherwise just restate the block below in different words — suppressed here so a
  // stalled queue with nothing else wrong shows exactly one alert, not two saying the same thing.
  const diagnosis = diagnoseWorkerHealth({ snap, capacity, replicas })
  const showDiagnosis = diagnosis && !diagnosis.message.includes('may not be actually claiming work')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, margin: '6px 0 10px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, flexWrap: 'wrap' }}>
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
          replicas?.configured ? (
            <span style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 4 }}>
              <span className="muted" style={{ fontSize: 11 }}>
                Azure warm replicas: {replicas.min_replicas}
                {replicas.max_replicas != null ? ` (max ${replicas.max_replicas})` : ''}
              </span>
              {onAdjustReplicas && (
                <>
                  <button onClick={() => onAdjustReplicas(-1)}
                          disabled={replicasBusy || replicas.min_replicas <= 1}
                          aria-label="Remove a warm replica"
                          style={{ width: 20, height: 20, borderRadius: 5, border: '1px solid var(--line)',
                                   background: '#fff', color: 'var(--ink)', fontSize: 14, lineHeight: 1,
                                   cursor: 'pointer', display: 'inline-flex', alignItems: 'center',
                                   justifyContent: 'center', padding: 0 }}>−</button>
                  <button onClick={() => onAdjustReplicas(1)}
                          disabled={replicasBusy || replicas.min_replicas >= 5}
                          aria-label="Add a warm replica"
                          style={{ width: 20, height: 20, borderRadius: 5, border: '1px solid var(--line)',
                                   background: '#fff', color: 'var(--ink)', fontSize: 14, lineHeight: 1,
                                   cursor: 'pointer', display: 'inline-flex', alignItems: 'center',
                                   justifyContent: 'center', padding: 0 }}>+</button>
                </>
              )}
              {replicasMsg && <span style={{ fontSize: 11,
                                              color: replicasMsg.startsWith('Failed') ? '#8A2A20' : '#1a7f37',
                                              fontWeight: 600, marginLeft: 2 }}>{replicasMsg}</span>}
            </span>
          ) : (
            <span className="muted" style={{ marginLeft: 4, fontStyle: 'italic' }}>
              Worker capacity is managed by your deployment administrator.
            </span>
          )
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
      {stalled && (
        <div role="alert" style={{ fontSize: 12, color: '#8A2A20', display: 'flex',
                                    alignItems: 'baseline', gap: 5 }}>
          <span aria-hidden="true">⚠</span>
          <span>
            Worker service reports online, but a queued job has been waiting {stalledAge}s —
            it may not be actually claiming work. Check Monitor.
          </span>
        </div>
      )}
      {showDiagnosis && (
        <div role="alert" style={{ fontSize: 12, color: diagnosis.severity === 'critical' ? '#8A2A20' : '#854F0B',
                                    display: 'flex', alignItems: 'baseline', gap: 5 }}>
          <span aria-hidden="true">⚠</span>
          <span>{diagnosis.message}</span>
        </div>
      )}
      {externallyManaged && capacity?.configured
       && (capacity.current_replicas != null || capacity.metrics_available
           || capacity.revision_health != null || capacity.draining_replicas) && (
        <div className="muted" style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {capacity.current_replicas != null && (
            <span>
              {capacity.current_replicas} replica{capacity.current_replicas === 1 ? '' : 's'} running now
            </span>
          )}
          {capacity.cpu_percent != null && <span>CPU {capacity.cpu_percent}%</span>}
          {capacity.memory_percent != null && <span>Memory {capacity.memory_percent}%</span>}
          {capacity.revision_health != null && (
            <span style={{ color: capacity.revision_health === 'Healthy' ? '#1a7f37' : '#8A2A20', fontWeight: 600 }}>
              Revision {capacity.revision_health.toLowerCase()}
            </span>
          )}
          {!!capacity.draining_replicas && (
            <span>{capacity.draining_replicas} replica{capacity.draining_replicas === 1 ? '' : 's'} draining from an older revision</span>
          )}
        </div>
      )}
    </div>
  )
}

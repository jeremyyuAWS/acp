import { describe, it, expect } from 'vitest'
import { diagnoseWorkerHealth } from './workerDiagnosis.js'
import { STALL_THRESHOLD_S } from './workerStallSignal.js'

const NOW = Date.parse('2026-08-29T02:00:00Z')

const okSnap = { workers: 4, alive: true, runtime_mode: 'auto', oldestQueuedCreatedAt: null,
                 workerHeartbeatAgeS: 5 }

describe('diagnoseWorkerHealth', () => {
  it('returns null when nothing is missing or wrong', () => {
    expect(diagnoseWorkerHealth({ snap: okSnap, nowMs: NOW })).toBeNull()
  })

  it('returns null when snap has not loaded yet', () => {
    expect(diagnoseWorkerHealth({ snap: null, nowMs: NOW })).toBeNull()
  })

  it('flags a worker tier that has never reported in', () => {
    const snap = { ...okSnap, alive: false, workerHeartbeatAgeS: null }
    const d = diagnoseWorkerHealth({ snap, nowMs: NOW })
    expect(d.severity).toBe('critical')
    expect(d.message).toMatch(/has ever reported in/)
  })

  it('flags Azure showing 0 replicas when offline and distributed, over the generic offline message', () => {
    const snap = { ...okSnap, alive: false, runtime_mode: 'distributed', workerHeartbeatAgeS: 300 }
    const capacity = { configured: true, current_replicas: 0 }
    const d = diagnoseWorkerHealth({ snap, capacity, nowMs: NOW })
    expect(d.severity).toBe('critical')
    expect(d.message).toMatch(/Azure shows 0 replicas running/)
  })

  it('does not use the Azure-specific offline message outside distributed mode', () => {
    const snap = { ...okSnap, alive: false, runtime_mode: 'auto', workerHeartbeatAgeS: 300 }
    const capacity = { configured: true, current_replicas: 0 }
    const d = diagnoseWorkerHealth({ snap, capacity, nowMs: NOW })
    expect(d.message).toMatch(/hasn't reported in/)
  })

  it('flags a generic stale heartbeat when offline with no Azure capacity data', () => {
    const snap = { ...okSnap, alive: false, workerHeartbeatAgeS: 245 }
    const d = diagnoseWorkerHealth({ snap, nowMs: NOW })
    expect(d.severity).toBe('critical')
    expect(d.message).toMatch(/hasn't reported in for 245s/)
    expect(d.message).toMatch(/crashed or was stopped/)
  })

  it('flags an unhealthy active revision ahead of any other online-state check', () => {
    const snap = { ...okSnap, workerHeartbeatAgeS: 5 }
    const capacity = { configured: true, revision_health: 'Unhealthy', current_replicas: 2 }
    const d = diagnoseWorkerHealth({ snap, capacity, nowMs: NOW })
    expect(d.severity).toBe('critical')
    expect(d.message).toMatch(/Unhealthy/)
  })

  it('flags a failed provisioning state', () => {
    const snap = { ...okSnap }
    const capacity = { configured: true, revision_health: 'Healthy', revision_provisioning_state: 'Failed',
                        current_replicas: 2 }
    const d = diagnoseWorkerHealth({ snap, capacity, nowMs: NOW })
    expect(d.message).toMatch(/failed to provision/)
  })

  it('flags configured-but-zero-running replicas while otherwise alive', () => {
    const snap = { ...okSnap }
    const capacity = { configured: true, revision_health: 'Healthy', current_replicas: 0 }
    const replicas = { configured: true, min_replicas: 2, max_replicas: 5 }
    const d = diagnoseWorkerHealth({ snap, capacity, replicas, nowMs: NOW })
    expect(d.severity).toBe('critical')
    expect(d.message).toMatch(/configured to keep 2 replicas warm, but none are currently running/)
  })

  it('singularizes "replica" for a min_replicas of one', () => {
    const snap = { ...okSnap }
    const capacity = { configured: true, current_replicas: 0 }
    const replicas = { configured: true, min_replicas: 1, max_replicas: 5 }
    const d = diagnoseWorkerHealth({ snap, capacity, replicas, nowMs: NOW })
    expect(d.message).toMatch(/keep 1 replica warm/)
  })

  it('flags a healthy revision stranded at 0% traffic — the stuck-rollout case', () => {
    const snap = { ...okSnap }
    const capacity = { configured: true, revision_health: 'Healthy', revision_provisioning_state: 'Provisioned',
                        current_replicas: 3, revision_traffic_percent: 0 }
    const d = diagnoseWorkerHealth({ snap, capacity, nowMs: NOW })
    expect(d.severity).toBe('critical')
    expect(d.message).toMatch(/receiving 0% of ingress traffic/)
  })

  it('does not flag 0% traffic when there are also zero replicas — that is the other rule\'s case', () => {
    const snap = { ...okSnap }
    const capacity = { configured: true, revision_health: 'Healthy', current_replicas: 0,
                        revision_traffic_percent: 0 }
    const replicas = { configured: true, min_replicas: 2, max_replicas: 5 }
    const d = diagnoseWorkerHealth({ snap, capacity, replicas, nowMs: NOW })
    expect(d.message).toMatch(/none are currently running/)
  })

  it('does not flag a partial traffic split as stranded', () => {
    const snap = { ...okSnap }
    const capacity = { configured: true, revision_health: 'Healthy', current_replicas: 2,
                        revision_traffic_percent: 20 }
    expect(diagnoseWorkerHealth({ snap, capacity, nowMs: NOW })).toBeNull()
  })

  it('does not flag anything when traffic data is unavailable', () => {
    const snap = { ...okSnap }
    const capacity = { configured: true, revision_health: 'Healthy', current_replicas: 2,
                        revision_traffic_percent: null }
    expect(diagnoseWorkerHealth({ snap, capacity, nowMs: NOW })).toBeNull()
  })

  it('warns when the heartbeat is aging toward the alive threshold', () => {
    const snap = { ...okSnap, workerHeartbeatAgeS: 75 }
    const d = diagnoseWorkerHealth({ snap, nowMs: NOW })
    expect(d.severity).toBe('warning')
    expect(d.message).toMatch(/75s old and getting close to the alive threshold/)
  })

  it('does not warn on heartbeat age below the aging threshold', () => {
    const snap = { ...okSnap, workerHeartbeatAgeS: 30 }
    expect(diagnoseWorkerHealth({ snap, nowMs: NOW })).toBeNull()
  })

  it('warns on a stalled queue when nothing else is wrong', () => {
    const createdAt = new Date(NOW - (STALL_THRESHOLD_S + 5) * 1000).toISOString()
    const snap = { ...okSnap, oldestQueuedCreatedAt: createdAt }
    const d = diagnoseWorkerHealth({ snap, nowMs: NOW })
    expect(d.severity).toBe('warning')
    expect(d.message).toMatch(/may not be actually claiming work/)
  })

  it('prioritizes heartbeat-aging over a stalled queue when both are true', () => {
    const createdAt = new Date(NOW - (STALL_THRESHOLD_S + 5) * 1000).toISOString()
    const snap = { ...okSnap, workerHeartbeatAgeS: 90, oldestQueuedCreatedAt: createdAt }
    const d = diagnoseWorkerHealth({ snap, nowMs: NOW })
    expect(d.message).toMatch(/getting close to the alive threshold/)
  })

  it('warns when capacity is pinned at max replicas with high CPU', () => {
    const snap = { ...okSnap }
    const capacity = { configured: true, current_replicas: 5, cpu_percent: 91, memory_percent: 40,
                        metrics_available: true }
    const replicas = { configured: true, min_replicas: 2, max_replicas: 5 }
    const d = diagnoseWorkerHealth({ snap, capacity, replicas, nowMs: NOW })
    expect(d.severity).toBe('warning')
    expect(d.message).toMatch(/Running at the configured max \(5\) replicas with 91% utilization/)
  })

  it('warns on high memory even when CPU is fine', () => {
    const snap = { ...okSnap }
    const capacity = { configured: true, current_replicas: 5, cpu_percent: 20, memory_percent: 88,
                        metrics_available: true }
    const replicas = { configured: true, min_replicas: 2, max_replicas: 5 }
    const d = diagnoseWorkerHealth({ snap, capacity, replicas, nowMs: NOW })
    expect(d.message).toMatch(/88% utilization/)
  })

  it('does not warn on high utilization when replicas have room to grow', () => {
    const snap = { ...okSnap }
    const capacity = { configured: true, current_replicas: 3, cpu_percent: 95, memory_percent: 90,
                        metrics_available: true }
    const replicas = { configured: true, min_replicas: 2, max_replicas: 5 }
    expect(diagnoseWorkerHealth({ snap, capacity, replicas, nowMs: NOW })).toBeNull()
  })

  it('does not warn on utilization when metrics are unavailable', () => {
    const snap = { ...okSnap }
    const capacity = { configured: true, current_replicas: 5, cpu_percent: null, memory_percent: null,
                        metrics_available: false }
    const replicas = { configured: true, min_replicas: 2, max_replicas: 5 }
    expect(diagnoseWorkerHealth({ snap, capacity, replicas, nowMs: NOW })).toBeNull()
  })

  it('returns null for the ordinary in-process mode with no capacity/replicas data at all', () => {
    expect(diagnoseWorkerHealth({ snap: okSnap, nowMs: NOW })).toBeNull()
  })
})

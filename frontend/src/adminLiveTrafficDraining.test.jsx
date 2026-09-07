import { describe, expect, it } from 'vitest'
import { drainingReplicasFact, infrastructureDetail, workerServiceRows } from './AdminLiveTraffic.jsx'

// A rollout mid-drain, as the backend reports it after #1652: the old replica is `occupied`,
// holds eight jobs, and contributes exactly eight slots; the new one is ready and idle.
function summaryMidDrain() {
  return {
    worker_roles: {},
    worker_capacity_by_role: {
      assess: {
        capacity_source: 'worker_instances', worker_slots: 28, busy_slots: 8, jobs_in_flight: 8,
        healthy_replicas: 1, occupied_replicas: 1, stale_replicas: 0, unattributed_running: 0,
        utilization_pct: 29, status: 'online',
        instances: [
          { replica_id: 'old', state: 'draining', occupied: true, healthy: false, active_job_count: 8, concurrency_limit: 8 },
          { replica_id: 'new', state: 'ready', occupied: false, healthy: true, active_job_count: 0, concurrency_limit: 20 },
        ],
      },
    },
  }
}

describe('A draining replica is named on the drawer, with the jobs it still holds', () => {
  it('sums the held jobs from the instances the backend marks occupied', () => {
    const [assess] = workerServiceRows(summaryMidDrain())
    expect(assess.occupied_replicas).toBe(1)
    expect(assess.occupied_jobs).toBe(8)
  })

  it('renders the sentence an operator needs mid-rollout', () => {
    const [assess] = workerServiceRows(summaryMidDrain())
    expect(drainingReplicasFact(assess)).toBe('1 draining, holding 8 jobs')
    const detail = infrastructureDetail({ kind: 'worker', label: 'Assess', service: assess }, { summary: summaryMidDrain() })
    expect(detail.facts).toContainEqual(['Draining replicas', '1 draining, holding 8 jobs'])
  })

  it('distinguishes "none draining" from "not reported"', () => {
    // Zero is a fact about a healthy lane; an absent field is a backend that predates it.
    // Reading the first as the second would make every quiet lane look under-instrumented.
    expect(drainingReplicasFact({ occupied_replicas: 0 })).toBe('None')
    expect(drainingReplicasFact({})).toBe('Not reported')
    expect(drainingReplicasFact({ occupied_replicas: 1, occupied_jobs: 1 })).toBe('1 draining, holding 1 job')
  })

  it('does not count jobs on replicas that are not occupied', () => {
    const summary = summaryMidDrain()
    summary.worker_capacity_by_role.assess.instances[1].active_job_count = 5   // ready replica, busy
    const [assess] = workerServiceRows(summary)
    expect(assess.occupied_jobs).toBe(8)
  })
})

/**
 * The redesigned Live Operations drawer, asserted at the DOM level.
 *
 * DOM rather than a browser screenshot on purpose: this repo's preview server serves the SHARED
 * checkout whatever worktree the change is in (CLAUDE.md), so a screenshot is evidence about main,
 * not about this branch. What is rendered here is what this branch actually produces.
 */
import { afterEach, describe, expect, it } from 'vitest'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import LiveOpsDrawer from './LiveOpsDrawer.jsx'

const NOW = Date.parse('2026-09-04T14:32:00Z')
const iso = (offsetS) => new Date(NOW + offsetS * 1000).toISOString()

const service = { role: 'assess', stage: 'assess', active: 2, slots: 3, available: 1, alive: true, age_s: 4, version: 'v25' }
const azureMetric = (label, rest, latest, series = [], available = true) => ({
  label, azure_metric: rest, available, latest, average: latest, unit: '',
  series: series.map(([offsetS, value]) => ({ at: iso(offsetS), value })),
})

const capacity = { configured: true, worker_app_name: 'acp-assess', current_replicas: 2,
  metrics_available: true, cpu_percent: 47, memory_percent: 67, measured_at: iso(-20),
  metrics_window_minutes: 15, metrics_interval: 'PT1M',
  active_revision_name: 'acp-assess--v25', revision_provisioning_state: 'Provisioned',
  metrics: {
    cpu_percent: azureMetric('CPU utilization', 'CpuPercentage', 54, [[-120, 40], [-60, 47], [0, 54]]),
    memory_percent: azureMetric('Memory utilization', 'MemoryPercentage', 67, [[-60, 63], [0, 67]]),
    replicas: azureMetric('Replica count', 'Replicas', 2, [[-60, 1], [0, 2]]),
    cpu_cores_used: azureMetric('CPU in use', 'UsageNanoCores', 1.5, [[-60, 1.2], [0, 1.5]]),
    working_set_bytes: azureMetric('Memory working set', 'WorkingSetBytes', 2147483648, [[0, 2147483648]]),
    restarts: azureMetric('Replica restarts', 'RestartCount', 3, [[-60, 1], [0, 3]]),
    network_in_bytes: azureMetric('Network in', 'RxBytes', 1048576, [[0, 1048576]]),
    network_out_bytes: azureMetric('Network out', 'TxBytes', 524288, [[0, 524288]]),
    reserved_cores: azureMetric('Reserved cores', 'TotalCoresQuotaUsed', null, [], false),
  } }

const snapshot = {
  generated_at: iso(-3),
  runs: [{ scan_id: 's1', stage: 'assess', source: 'drive', owner: 'operator@example.org',
    completed: 8, total: 20, running: 2, queued: 10, status: 'active',
    current_file: 'Mediation Record 11.13.2022.xlsx', current_rule_id: 'WCAG 1.3.1',
    oldest_queued_at: iso(-200), updated_at: iso(-4), started_at: iso(-600) }],
  summary: {
    active_runs: 1, recent_runs: 0, active_users: 1, waiting_users: 2, queued: 10, running: 2,
    completed_jobs: 140, worker_slots: 7, available_slots: 5, utilization_pct: 28,
    pressure: 'busy', scheduling_policy: 'tenant_fair_least_loaded', worker_tier_alive: true,
    by_stage: { assess: { running: 2, queued: 10, completed: 8, total: 20 },
      remediate: { completed: 12, running: 1 }, release: { completed: 9, running: 0 } },
    worker_roles: { assess: { alive: true, pool_size: 3, age_s: 4, version: 'v25' } },
    queue: { running: 2, waiting: 8, retrying: 2, failed: 1, arrived: 30, completed: 45,
      window_s: 900, oldest_queued_at: iso(-200) },
  },
}

const samples = [
  { at: iso(-240), active_jobs: 1, queue_depth: 12, completed: 2, cpu_pct: 40, memory_pct: 55, replicas: 1, failure_pct: null, oldest_wait_s: 40 },
  { at: iso(-120), active_jobs: 2, queue_depth: 11, completed: 5, cpu_pct: 50, memory_pct: 60, replicas: 2, failure_pct: null, oldest_wait_s: 90 },
  { at: iso(-3), active_jobs: 2, queue_depth: 10, completed: 8, cpu_pct: 54, memory_pct: 67, replicas: 2, failure_pct: null, oldest_wait_s: 200 },
]

const events = [
  { id: 'e3', at: iso(-3), kind: 'activity', stage: 'assess', nodes: ['stage:assess', 's1:assess'],
    text: 'Worker claimed Mediation Record 11.13.2022.xlsx', outcome: 'Claimed', correlation: 's1' },
  { id: 'e2', at: iso(-40), kind: 'capacity', nodes: ['stage:assess'],
    text: 'assess worker slots changed from 2 to 3', outcome: 'Scaled up', correlation: 'assess' },
  { id: 'e1', at: iso(-90), kind: 'error', nodes: ['infra:queue'],
    text: '1 job dead-lettered', outcome: 'Failed', correlation: 'shared-queue' },
]

afterEach(unmountAll)

const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => {
    root.render(createElement(LiveOpsDrawer, {
      snapshot, capacity, connection: 'live', samples, events, nowMs: NOW,
      onClose: () => {}, ...props,
    }))
  })
  return container
}

const click = async (element) => { await act(async () => { element.click() }) }
const buttonNamed = (container, text) =>
  [...container.querySelectorAll('button')].find((b) => b.textContent.trim() === text)

describe('Live header', () => {
  it('names the component, its type, its state in words, and when it last updated', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: { kind: 'worker', label: 'Assess workers', service } })
    const dialog = container.querySelector('[role="dialog"]')
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(dialog.textContent).toContain('Assess workers')
    expect(dialog.textContent).toContain('Worker service')
    expect(dialog.textContent).toContain('Online')
    expect(dialog.textContent).toContain('Updated 3s ago')
    expect(dialog.textContent).toContain('Live stream connected')
    expect(dialog.textContent).toContain('Deployment revision: acp-assess--v25')
    expect(buttonNamed(container, 'View full Live Operations')).toBeTruthy()
  })

  it('animates the live indicator only while the stream is actually connected', async () => {
    const live = await mount({ nodeId: 'stage:assess', node: { kind: 'worker', label: 'Assess workers', service } })
    expect(live.querySelector('.liveops-pulse')).toBeTruthy()
    const dropped = await mount({ nodeId: 'stage:assess', connection: 'reconnecting',
      node: { kind: 'worker', label: 'Assess workers', service } })
    expect(dropped.querySelector('.liveops-pulse')).toBe(null)
    expect(dropped.textContent).toContain('Live stream reconnecting')
  })

  it('states an offline service in text, not by colour alone', async () => {
    const container = await mount({ nodeId: 'stage:assess',
      node: { kind: 'worker', label: 'Assess workers', service: { ...service, alive: false } } })
    expect(container.textContent).toContain('Offline')
    expect(container.textContent).toContain('No heartbeat within the liveness window')
  })
})

describe('Primary visualization per node', () => {
  it('draws a worker utilization gauge with its text equivalent and its threshold rule', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: { kind: 'worker', label: 'Assess workers', service } })
    const gauge = container.querySelector('svg[aria-label*="worker slots active"]')
    expect(gauge).toBeTruthy()
    expect(gauge.getAttribute('aria-label')).toBe('2 of 3 worker slots active (67%), 1 available')
    // 2 of 3 is 67%, below the documented 75% amber band — the gauge says capacity is available.
    expect(container.textContent).toContain('Capacity available')
    expect(container.textContent).toContain('Amber from 75% of slots, red at 100%')
  })

  it('does not render an impossible utilisation percentage', async () => {
    // The screenshot that prompted this: "51 of 2 worker slots active (2550%)".
    const container = await mount({ nodeId: 'stage:assess',
      node: { kind: 'worker', label: 'Assess workers', service: { ...service, active: 51, slots: 2, available: 0 } } })
    expect(container.textContent).not.toContain('2550')
    expect(container.textContent).toContain('Over committed')
    expect(container.textContent).toContain('51 jobs in flight against 2 reported worker slots')
    expect(container.textContent).toContain('last-writer-wins across replicas')
  })

  it('bands the gauge amber once the documented threshold is crossed', async () => {
    const container = await mount({ nodeId: 'stage:assess',
      node: { kind: 'worker', label: 'Assess workers', service: { ...service, active: 3, slots: 4 } } })
    expect(container.textContent).toContain('Approaching capacity')
  })

  it('draws the queue as its four states with the rates and the tenant warning', async () => {
    const container = await mount({ nodeId: 'infra:queue', node: { kind: 'queue', label: 'Shared queue' } })
    const bar = container.querySelector('[aria-label*="running"]')
    expect(bar.getAttribute('aria-label')).toBe('2 running, 8 waiting, 2 retrying, 1 failed / dead-lettered')
    expect(container.textContent).toContain('Retrying')
    expect(container.textContent).toContain('3m 20s')          // oldest wait
    expect(container.textContent).toContain('2/min')            // arrivals
    expect(container.textContent).toContain('3/min')            // completions
    expect(container.textContent).toContain('USERS WAITING')
    expect(container.textContent).toContain('Tenant concentration')
  })

  it('draws run progress radially, with an estimate only when the samples support one', async () => {
    const node = { kind: 'run', run: snapshot.runs[0] }
    const container = await mount({ nodeId: 's1:assess', node })
    expect(container.querySelector('svg[aria-label="8 of 20 documents complete"]')).toBeTruthy()
    expect(container.textContent).toContain('40%')
    expect(container.textContent).toContain('Mediation Record 11.13.2022.xlsx')
    expect(container.textContent).toContain('WCAG 1.3.1')
    // 6 documents over 237s with 12 remaining → about 8 minutes.
    expect(container.textContent).toMatch(/ESTIMATED REMAINING\s*7m/)
    const thin = await mount({ nodeId: 's1:assess', node, samples: samples.slice(-1) })
    expect(thin.textContent).toContain('Not enough evidence')
  })

  it('shows a source connector health and names what it cannot measure', async () => {
    const container = await mount({ nodeId: 'source:drive',
      node: { kind: 'source', label: 'Google Drive', source: 'drive', active: 1 } })
    expect(container.textContent).toContain('Connection health')
    expect(container.textContent).toContain('ACTIVE RUNS')
    expect(container.textContent).toContain('RECENT THROTTLING')
    expect(container.textContent).toContain('AUTHENTICATION FRESHNESS')
    expect(container.textContent).toContain('Not reported')
  })

  it('shows durable output counts and refuses a total size Azure did not report', async () => {
    const container = await mount({ nodeId: 'infra:output', node: { kind: 'output', label: 'Durable outputs' } })
    expect(container.textContent).toContain('CORRECTED COPIES PRODUCED')
    expect(container.textContent).toMatch(/TOTAL OUTPUT SIZE\s*Not reported/)
    expect(container.textContent).toContain('Original source documents are never modified')
  })
})

describe('Every worker service shows its own Azure numbers', () => {
  const perApp = (name, cpu) => ({ configured: true, worker_app_name: name, measured_at: iso(-20),
    current_replicas: 2, metrics_window_minutes: 15,
    metrics: { restarts: azureMetric('Replica restarts', 'RestartCount', cpu) } })
  const multi = { ...capacity, apps: {
    'acp-discovery': perApp('acp-discovery', 7),
    'acp-assess': perApp('acp-assess', 3),
    'acp-remediate': perApp('acp-remediate', 11) } }

  it('shows the discover service own restarts rather than suppressing them', async () => {
    // Before the multi-app read this panel said "Azure measured acp-assess, not this service".
    const container = await mount({ nodeId: 'stage:discover', capacity: multi,
      node: { kind: 'worker', label: 'Discover workers',
        service: { ...service, role: 'discovery', stage: 'discover' } } })
    expect(container.textContent).not.toContain('not this service')
    expect(container.textContent).toContain('REPLICA RESTARTS')
    expect(container.textContent).toContain('7')
  })

  it('keeps each service on its own app numbers', async () => {
    // Asserted on the tile itself: "11" also occurs in the filename on this page, and a
    // whole-page substring check would pass or fail for the wrong reason.
    const restarts = (container) => [...container.querySelectorAll('div')]
      .map((el) => el.textContent)
      .find((text) => text.startsWith('REPLICA RESTARTS'))
    const assess = await mount({ nodeId: 'stage:assess', capacity: multi,
      node: { kind: 'worker', label: 'Assess workers', service } })
    expect(restarts(assess)).toContain('3')
    expect(restarts(assess)).not.toContain('11')
    const remediate = await mount({ nodeId: 'stage:remediate', capacity: multi,
      node: { kind: 'worker', label: 'Remediate workers',
        service: { ...service, role: 'remediate', stage: 'remediate' } } })
    expect(restarts(remediate)).toContain('11')
  })

  it('still declines for a service no configured app describes', async () => {
    const container = await mount({ nodeId: 'stage:release', capacity: multi,
      node: { kind: 'worker', label: 'Release workers',
        service: { ...service, role: 'release', stage: 'release' } } })
    expect(container.textContent).toContain('not this service')
  })
})

describe('Azure Monitor in the drawer', () => {
  const workerNode = { kind: 'worker', label: 'Assess workers', service }

  it('shows what Azure actually reports about this service app', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode })
    expect(container.textContent).toContain('REPLICA RESTARTS')
    expect(container.textContent).toContain('Azure metric RestartCount')
    expect(container.textContent).toContain('NETWORK IN')
    expect(container.textContent).toContain('1 MB')            // bytes rendered as bytes
    expect(container.textContent).toContain('2 GB')            // working set
    expect(container.textContent).toContain('1.5 cores')
  })

  it('names a metric Azure did not answer for rather than showing it as zero', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode })
    expect(container.textContent).toMatch(/RESERVED CORES\s*Not reported/)
  })

  it('refuses to show one container app measurements as another service own', async () => {
    // Production runs three differently sized worker apps and WORKER_APP_NAME names one.
    const container = await mount({ nodeId: 'stage:discover',
      node: { kind: 'worker', label: 'Discover workers', service: { ...service, role: 'discovery', stage: 'discover' } } })
    expect(container.textContent).toContain('Azure Monitor measured')
    expect(container.textContent).toContain('not this service')
    expect(container.textContent).not.toContain('REPLICA RESTARTS')
  })

  it('says so plainly when Azure is not configured at all', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, capacity: { configured: false } })
    expect(container.textContent).toContain('Azure Monitor is not configured')
  })

  it('plots Azure own history rather than the minute this tab has been open', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode })
    await click(buttonNamed(container, 'CPU utilization'))
    // Three Azure points, not the browser's own samples — which carry no cpu at all here.
    expect(container.querySelectorAll('circle[tabindex="0"]').length).toBe(3)
    expect(container.textContent).toContain('Azure Monitor · 1 min interval · 20s ago')
  })

  it('separates a two-second ACP reading from a one-minute Azure sample in the picker', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode })
    expect(container.querySelector('[aria-label="ACP live metrics"]')).toBeTruthy()
    expect(container.querySelector('[aria-label="Azure Monitor metrics"]')).toBeTruthy()
  })
})

describe('Provenance', () => {
  it('labels a live reading with its age and an unmeasured one as unavailable', async () => {
    const container = await mount({ nodeId: 'infra:queue', node: { kind: 'queue', label: 'Shared queue' } })
    expect(container.textContent).toContain('Live · ACP event stream · 3s ago')
    const output = await mount({ nodeId: 'infra:output', node: { kind: 'output', label: 'Durable outputs' } })
    expect(output.textContent).toContain('Not reported · no measurement available')
  })

  it('never labels an Azure reading as live, and says which Azure surface it came from', async () => {
    const container = await mount({ nodeId: 'stage:assess',
      node: { kind: 'worker', label: 'Assess workers', service } })
    const azureLines = [...container.querySelectorAll('div')]
      .filter((el) => el.textContent.startsWith('Azure Monitor ·'))
      .map((el) => el.textContent)
    expect(azureLines.length).toBeGreaterThan(0)
    expect(azureLines.some((text) => text.includes('Live ·'))).toBe(false)
    // Two different Azure surfaces with two different cadences: metrics are sampled at PT1M,
    // while replica and revision state is a control-plane read taken when the reading is. Giving
    // both the metric interval would overstate how often the lifecycle is resampled.
    expect(azureLines.some((text) => text.includes('1 min interval'))).toBe(true)
    expect(azureLines.some((text) => text.includes('Container Apps control plane'))).toBe(true)
  })
})

describe('Current work, attributed to a service and not to a replica', () => {
  const workerNode = { kind: 'worker', label: 'Assess workers', service }
  const working = { ...snapshot, summary: { ...snapshot.summary,
    worker_instance_attribution: { available: false,
      reason: 'ACP does not record which replica ran a job. The worker_instances registry exists but has no writer yet, so job activity is attributed to a service, not to one of its replicas.' } },
    runs: [{ ...snapshot.runs[0], current_job_started_at: iso(-45),
      current_job_type: 'scan_file', last_error_class: 'source_rate_limit', max_attempts_seen: 2 }] }

  it('shows the file, the criterion and how long a worker has actually been on it', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, snapshot: working })
    expect(container.textContent).toContain('Current work')
    expect(container.textContent).toContain('Mediation Record 11.13.2022.xlsx')
    expect(container.textContent).toContain('WCAG 1.3.1')
    // From the claim instant, not from the status — 'running' alone cannot say how long.
    expect(container.textContent).toContain('running 45s')
  })

  it('names a classified failure in an operator words, with the retry count', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, snapshot: working })
    expect(container.textContent).toContain('Last failure: Source rate limit')
    expect(container.textContent).toContain('2 retries')
  })

  it('says ACP cannot attribute a job to a replica, rather than implying it can', async () => {
    // The replica list sits directly above this panel; without the sentence a reader would
    // reasonably assume the two join.
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, snapshot: working })
    expect(container.textContent).toContain('attributed to a service, not to one of its replicas')
  })

  it('says nothing is being processed rather than rendering an empty list', async () => {
    const idle = { ...working, runs: [] }
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, snapshot: idle })
    expect(container.textContent).toContain('No job is being processed by this service right now')
  })

  it('does not claim a runtime when the claim instant is not reported', async () => {
    const noClaim = { ...working, runs: [{ ...working.runs[0], current_job_started_at: null }] }
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, snapshot: noClaim })
    expect(container.textContent).toContain('claim time not reported')
  })
})

describe('Worker saturation', () => {
  const workerNode = { kind: 'worker', label: 'Assess workers', service }
  const busy = { ...snapshot, summary: { ...snapshot.summary,
    by_stage: { ...snapshot.summary.by_stage, assess: { running: 2, queued: 10, completed: 8, total: 20 } } } }
  const drainSamples = [
    { at: iso(-120), active_jobs: 2, queue_depth: 12, completed: 4 },
    { at: iso(0), active_jobs: 2, queue_depth: 10, completed: 12 },
  ]

  it('shows ACP worker slots and Azure replicas as two separate capacities', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, snapshot: busy })
    expect(container.textContent).toContain('WORKER SLOTS')
    expect(container.textContent).toContain('2 of 3 busy')
    expect(container.textContent).toContain('REPLICAS')
    expect(container.textContent).toContain('SCALE HEADROOM')
  })

  it('estimates the drain from this service own completions', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, snapshot: busy,
      samples: drainSamples })
    // 8 completed over 120s with 10 waiting → 2m 30s.
    expect(container.textContent).toContain('TIME TO CLEAR QUEUE')
    expect(container.textContent).toContain('2m 30s')
  })

  it('says why it has no drain time rather than leaving the tile blank', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, snapshot: busy,
      samples: [{ at: iso(-120), completed: 4 }, { at: iso(0), completed: 4 }] })
    expect(container.textContent).toContain('Not enough evidence')
    expect(container.textContent).toContain('30s of samples with completions')
  })
})

describe('Replica lifecycle', () => {
  const workerNode = { kind: 'worker', label: 'Assess workers', service }
  const lifecycleCapacity = { ...capacity,
    replicas: [
      { name: 'r1', revision: 'acp-assess--v25', state: 'ready', age_s: 3600, restarts: 0,
        containers_ready: 1, containers: 1, image: 'acr.io/acp-assess:v25', state_detail: null },
      { name: 'r2', revision: 'acp-assess--v25', state: 'starting', age_s: 20, restarts: 2,
        containers_ready: 0, containers: 1, image: 'acr.io/acp-assess:v25', state_detail: null },
      { name: 'r0', revision: 'acp-assess--v24', state: 'draining', age_s: 7200, restarts: 0,
        containers_ready: 1, containers: 1, image: 'acr.io/acp-assess:v24', state_detail: null },
    ],
    revisions: [
      { name: 'acp-assess--v25', active: true, health: 'Healthy', provisioning_state: 'Provisioned',
        provisioning_error: null, traffic_percent: 100, replicas: 2, age_s: 1800 },
      { name: 'acp-assess--v24', active: false, health: 'Healthy', provisioning_state: 'Provisioned',
        provisioning_error: null, traffic_percent: 0, replicas: 1, age_s: 7200 },
    ],
    replica_lifecycle: {
      counts: { ready: 1, starting: 1, allocating: 0, not_running: 0, draining: 1, unknown: 0 },
      total: 3, unreported_states: ['requested', 'failed'],
      unreported_reason: "Azure Container Apps does not list pending or removed replicas; a failure surfaces on the revision's provisioningState and provisioningError instead.",
    } }

  it('shows what each replica is doing, how long it has been up, and what it is running', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, capacity: lifecycleCapacity })
    expect(container.textContent).toContain('Replica lifecycle')
    expect(container.textContent).toContain('3 replicas reported')
    expect(container.textContent).toContain('Starting')
    expect(container.textContent).toContain('Draining')
    expect(container.textContent).toContain('up 1h 0m')
    expect(container.textContent).toContain('2 restarts')
    expect(container.textContent).toContain('acr.io/acp-assess:v25')
  })

  it('says which states Azure does not report, instead of showing them as zero', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, capacity: lifecycleCapacity })
    expect(container.textContent).toContain('Not counted: requested and failed')
    expect(container.textContent).toContain('does not list pending or removed replicas')
  })

  it('lists every revision with its traffic share, so a stuck rollout is visible', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, capacity: lifecycleCapacity })
    expect(container.textContent).toContain('acp-assess--v25')
    expect(container.textContent).toContain('100% traffic')
    expect(container.textContent).toContain('0% traffic')
  })

  it('surfaces a failed rollout with Azure own error string', async () => {
    // A failed replica is simply absent from list_replicas, so without this the app reads as one
    // that merely has fewer replicas than expected.
    const failed = { ...lifecycleCapacity, replicas: [],
      replica_lifecycle: { ...lifecycleCapacity.replica_lifecycle, total: 0,
        counts: { ready: 0, starting: 0, allocating: 0, not_running: 0, draining: 0, unknown: 0 } },
      revisions: [{ name: 'acp-assess--v26', active: true, health: 'Unhealthy',
        provisioning_state: 'Failed', provisioning_error: 'ImagePullFailure: manifest unknown',
        traffic_percent: 100, replicas: 0, age_s: 240 }] }
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, capacity: failed })
    expect(container.textContent).toContain('Active revision is Failed')
    expect(container.textContent).toContain('ImagePullFailure: manifest unknown')
    expect(container.textContent).toContain('created 4m 0s ago')
  })

  it('refuses to show another container app replicas as this service own', async () => {
    const container = await mount({ nodeId: 'stage:discover', capacity: lifecycleCapacity,
      node: { kind: 'worker', label: 'Discover workers', service: { ...service, role: 'discovery', stage: 'discover' } } })
    expect(container.textContent).toContain('not this service')
    expect(container.textContent).not.toContain('acr.io/acp-assess:v25')
  })

  it('says so when Azure is not configured rather than showing an empty lifecycle', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, capacity: { configured: false } })
    expect(container.textContent).toContain('replica lifecycle is unavailable')
  })
})

describe('Throughput panel', () => {
  const counters = [
    { at: iso(-600), documents: 70, fixes: 4, findings: 10 },
    { at: iso(-300), documents: 100, fixes: 8, findings: 22 },
    { at: iso(-299), documents: 100, fixes: 8, findings: 22 },
    { at: iso(0), documents: 160, fixes: 20, findings: 22 },
  ]

  it('shows each rate against the five minutes before it', async () => {
    const container = await mount({ nodeId: 'infra:queue', node: { kind: 'queue', label: 'Shared queue' },
      samples: counters })
    expect(container.textContent).toContain('Throughput')
    expect(container.textContent).toContain('12/min')                 // documents now
    expect(container.textContent).toContain('vs previous 5 min')
  })

  it('says which half is missing rather than leaving a blank cell', async () => {
    const container = await mount({ nodeId: 'infra:queue', node: { kind: 'queue', label: 'Shared queue' },
      samples: [{ at: iso(-240), documents: 100 }, { at: iso(0), documents: 160 }] })
    expect(container.textContent).toContain('needs a full 5 minutes before this one')
  })

  it('reports a metric nobody counted as not reported', async () => {
    const container = await mount({ nodeId: 'infra:queue', node: { kind: 'queue', label: 'Shared queue' },
      samples: [{ at: iso(-300), documents: 100 }, { at: iso(0), documents: 160 }] })
    const findings = [...container.querySelectorAll('li')].map((el) => el.textContent)
      .find((text) => text.startsWith('Findings'))
    expect(findings).toContain('Not reported')
  })
})

describe('Trend strip', () => {
  const workerNode = { kind: 'worker', label: 'Assess workers', service }

  it('plots the last fifteen minutes with labelled axes and the current value', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode })
    const chart = container.querySelector('svg[aria-label*="over the last 15 minutes"]')
    expect(chart).toBeTruthy()
    expect(chart.textContent).toContain('15 min ago')
    expect(chart.textContent).toContain('now')
    expect(container.textContent).toContain('Last 15 minutes')
    expect(chart.querySelectorAll('polyline').length).toBeGreaterThan(0)
  })

  it('switches metric, and says so rather than plotting a metric this node does not report', async () => {
    const container = await mount({ nodeId: 'infra:queue', node: { kind: 'queue', label: 'Shared queue' } })
    await click(buttonNamed(container, 'Failure rate'))
    expect(container.textContent).toContain('Failure rate is not reported for this component.')
    expect(container.querySelector('svg[aria-label*="over the last 15 minutes"]')).toBe(null)
  })

  it('refuses a line when only one sample has arrived', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, samples: samples.slice(-1) })
    expect(container.textContent).toContain('Collecting samples — one measurement so far')
  })

  it('gives every point a focusable tooltip with its timestamp and value', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode })
    const points = [...container.querySelectorAll('circle[tabindex="0"]')]
    expect(points.length).toBe(3)
    expect(points.at(-1).getAttribute('aria-label')).toMatch(/^\d{2}:\d{2}:\d{2}: 2$/)
    await act(async () => { points[0].dispatchEvent(new window.FocusEvent('focus', { bubbles: true })) })
    expect(container.querySelector('[aria-live="polite"]').textContent).toMatch(/— 1$/)
  })

  it('marks the scaling moment it observed on the timeline', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode })
    expect(container.textContent).toContain('Dashed markers: deployment and scaling moments')
    expect(container.querySelectorAll('line[stroke-dasharray]').length).toBe(1)
  })
})

describe('Event timeline', () => {
  const workerNode = { kind: 'worker', label: 'Assess workers', service }

  it('lists this component events newest first, with time, icon, outcome and correlation', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode })
    const items = [...container.querySelectorAll('ol li')]
    expect(items).toHaveLength(2)
    expect(items[0].textContent).toContain('Worker claimed Mediation Record 11.13.2022.xlsx')
    expect(items[0].textContent).toContain('Claimed')
    expect(items[1].textContent).toContain('Scaled up')
    // The dead-letter event belongs to the queue, not to this worker service.
    expect(container.textContent).not.toContain('dead-lettered')
  })

  it('filters by category', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode })
    await click(buttonNamed(container, 'Capacity'))
    const items = [...container.querySelectorAll('ol li')]
    expect(items).toHaveLength(1)
    expect(items[0].textContent).toContain('slots changed from 2 to 3')
  })

  it('pauses and resumes visual updates without stopping the data behind them', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode })
    await click(buttonNamed(container, 'Pause visual updates'))
    const resume = buttonNamed(container, 'Resume visual updates')
    expect(resume.getAttribute('aria-pressed')).toBe('true')
    expect(container.textContent).toContain('the list below is frozen')
    await click(resume)
    expect(buttonNamed(container, 'Pause visual updates')).toBeTruthy()
  })

  it('copies a correlation identifier on request', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode })
    await click(buttonNamed(container, 'Copy correlation ID'))
    expect(container.textContent).toContain('Copied')
  })

  it('says where its events come from, and shows no document contents', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode })
    expect(container.textContent).toContain('derived from changes observed between live snapshots')
    expect(container.textContent).toContain('Document contents, tokens and credentials are never shown')
  })

  it('explains an empty timeline rather than looking broken', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, events: [] })
    expect(container.textContent).toContain('No events observed for this component yet')
  })
})

describe('Dialog behaviour', () => {
  it('closes on Escape, on the scrim, and on the close button', async () => {
    for (const dismiss of ['escape', 'scrim', 'button']) {
      let closed = false
      const container = await mount({ nodeId: 'stage:assess',
        node: { kind: 'worker', label: 'Assess workers', service }, onClose: () => { closed = true } })
      if (dismiss === 'escape') {
        await act(async () => {
          window.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
        })
      } else if (dismiss === 'scrim') {
        await click(container.querySelector('button[aria-label="Close component details"]'))
      } else {
        await click(buttonNamed(container, 'Close'))
      }
      expect(closed, dismiss).toBe(true)
    }
  })

  it('moves focus into the dialog so a keyboard user is not left behind on the map', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: { kind: 'worker', label: 'Assess workers', service } })
    expect(container.querySelector('[role="dialog"]').contains(document.activeElement)).toBe(true)
  })
})

describe('Detailed facts are preserved, not discarded', () => {
  it('keeps the operational fact tiles available for inspection', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: { kind: 'worker', label: 'Assess workers', service },
      facts: [['Service health', 'Online'], ['Replica size', '2 vCPU · 4Gi RAM · 8Gi temporary disk']] })
    const details = container.querySelector('details')
    expect(details.textContent).toContain('Operational facts')
    expect(details.textContent).toContain('2 vCPU · 4Gi RAM · 8Gi temporary disk')
    expect(details.textContent).toContain('are never estimated')
  })
})

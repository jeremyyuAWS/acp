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
      window_s: 900, oldest_queued_at: iso(-200), median_queued_at: iso(-90),
      p95_queued_at: iso(-185), wait_sampled: 10,
      fairness: { tenants: 3, counts: [8, 5, 2], top_share_pct: 53 } },
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
    // The header now names one of four explicit stream states — see streamState. "Live" plus
    // the sentence under it replaces the old single "Live stream connected" string.
    expect(dialog.textContent).toContain('Live')
    expect(dialog.textContent).toContain('Receiving live updates.')
    expect(dialog.textContent).toContain('Deployment revision: acp-assess--v25')
    expect(buttonNamed(container, 'View full Live Operations')).toBeTruthy()
  })

  it('animates the live indicator only while the stream is actually connected', async () => {
    const live = await mount({ nodeId: 'stage:assess', node: { kind: 'worker', label: 'Assess workers', service } })
    expect(live.querySelector('.liveops-pulse')).toBeTruthy()
    const dropped = await mount({ nodeId: 'stage:assess', connection: 'reconnecting',
      node: { kind: 'worker', label: 'Assess workers', service } })
    expect(dropped.querySelector('.liveops-pulse')).toBe(null)
    expect(dropped.textContent).toContain('Reconnecting')
    expect(dropped.textContent).toMatch(/last frame received/)
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
    // CHANGED DELIBERATELY, per the brief: the gauge is bounded at 100% and the excess is its
    // own figure, so the reader gets both true facts instead of neither.
    expect(container.textContent).toContain('2 of 2 slots busy (100%)')
    expect(container.textContent).toContain('49 more jobs running than slots')
    expect(container.textContent).not.toContain('51 of 2')
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

  it('shows the median and the tail alongside the worst job', async () => {
    const container = await mount({ nodeId: 'infra:queue', node: { kind: 'queue', label: 'Shared queue' } })
    expect(container.textContent).toContain('MEDIAN WAIT')
    expect(container.textContent).toContain('1m 30s')
    expect(container.textContent).toContain('95TH PERCENTILE WAIT')
    expect(container.textContent).toContain('Across 10 claimable jobs')
  })

  it('names the stage that can claim the waiting work, bounded at 100% with the excess as backlog', async () => {
    const container = await mount({ nodeId: 'infra:queue', node: { kind: 'queue', label: 'Shared queue' } })
    const panel = container.querySelector('[aria-label="Worker capacity able to claim this queue"]')
    expect(panel).toBeTruthy()
    expect(panel.textContent).toContain('assess')
    expect(panel.textContent).toContain('10 waiting for 3 slots')
    // 10 jobs against 3 slots is 100% busy with 7 behind it — NOT 333% utilized.
    expect(panel.textContent).toContain('100% of this stage’s slots')
    expect(panel.textContent).toContain('7 beyond capacity (backlog, not utilization)')
    expect(panel.textContent).not.toContain('333')
    expect(panel.querySelector('[aria-label="assess: 100% of 3 slots claimable now, 7 jobs beyond capacity"]')).toBeTruthy()
  })

  it('says a stage is not reporting slots rather than drawing it at zero', async () => {
    const summary = { ...snapshot.summary, queued: 12,
      by_stage: { ...snapshot.summary.by_stage, remediate: { completed: 12, running: 1, queued: 2 } } }
    const container = await mount({ nodeId: 'infra:queue', node: { kind: 'queue', label: 'Shared queue' },
      snapshot: { ...snapshot, summary } })
    const panel = container.querySelector('[aria-label="Worker capacity able to claim this queue"]')
    expect(panel.textContent).toContain('remediate')
    expect(panel.textContent).toContain('slots Not reported')
    expect(panel.textContent).toContain('unknown — not zero')
    // One bar for assess (which reports a pool), none for remediate (which does not).
    expect(panel.querySelectorAll('[role="img"]').length).toBe(1)
  })

  it('says a stage scaled to zero can claim nothing, rather than drawing a bar of null width', async () => {
    // Reachable: a stage scaled to zero replicas still heartbeats, so its pool_size is a MEASURED
    // 0, not an absent reading. Dividing by it produced `width: null%` and an aria-label reading
    // "null% of 0 slots".
    const summary = { ...snapshot.summary,
      worker_roles: { assess: { alive: true, pool_size: 0, age_s: 4, version: 'v25' } } }
    const container = await mount({ nodeId: 'infra:queue', node: { kind: 'queue', label: 'Shared queue' },
      snapshot: { ...snapshot, summary } })
    const panel = container.querySelector('[aria-label="Worker capacity able to claim this queue"]')
    expect(panel.textContent).toContain('zero worker slots, so nothing can claim its 10 waiting jobs')
    expect(panel.querySelectorAll('[role="img"]').length).toBe(0)
    expect(panel.innerHTML).not.toContain('null%')
  })

  it('counts waiting work no stage claimed instead of adding it to a role', async () => {
    const summary = { ...snapshot.summary, queued: 14 }   // 10 attributed to assess, 4 to nobody
    const container = await mount({ nodeId: 'infra:queue', node: { kind: 'queue', label: 'Shared queue' },
      snapshot: { ...snapshot, summary } })
    const panel = container.querySelector('[aria-label="Worker capacity able to claim this queue"]')
    expect(panel.textContent).toContain('4 waiting jobs the snapshot did not attribute to a stage')
    expect(panel.textContent).toContain('10 waiting for 3 slots')   // assess is unchanged by it
  })

  it('draws the tenant split as a shape and never names a customer', async () => {
    const container = await mount({ nodeId: 'infra:queue', node: { kind: 'queue', label: 'Shared queue' } })
    expect(container.textContent).toContain('Fairness')
    expect(container.textContent).toContain('3 tenants waiting')
    expect(container.textContent).toContain('tenants are counted, never named')
    expect(container.querySelector('[aria-label^="Waiting work split across 3 tenants"]')).toBeTruthy()
    expect(container.textContent).not.toMatch(/@example/)
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

  const runNode = { kind: 'run', run: snapshot.runs[0] }

  it('labels the remaining-time figure as an estimate, and names what it projects from', async () => {
    // WRITTEN WRONG FIRST, and the bite-check caught it: the original asserted /estimate/i against
    // the whole tile, which the LABEL "ESTIMATED REMAINING" satisfies on its own — so it passed
    // with the provenance line deleted. The assertion has to name the provenance text.
    const container = await mount({ nodeId: 's1:assess', node: runNode })
    const eta = [...container.querySelectorAll('div')]
      .find((d) => d.textContent.startsWith('ESTIMATED REMAINING'))
    expect(eta.textContent).toContain('projected from completions observed in this session')
    // And it must not borrow the OTHER estimate's basis: this one is not from configured capacity.
    expect(eta.textContent).not.toContain('configured capacity')
  })

  it('says the remaining time is not reported when the samples cannot support one', async () => {
    const thin = await mount({ nodeId: 's1:assess', node: runNode, samples: samples.slice(-1) })
    const eta = [...thin.querySelectorAll('div')]
      .find((d) => d.textContent.startsWith('ESTIMATED REMAINING'))
    expect(eta.textContent).toContain('Not enough evidence')
    // No projection label on a figure there is no projection for.
    expect(eta.textContent).not.toContain('projected from completions')
  })

  it('draws the four document states as one bar and lists them all', async () => {
    const container = await mount({ nodeId: 's1:assess', node: runNode })
    const bar = container.querySelector('[aria-label="8 completed, 2 processing, 10 waiting"]')
    expect(bar).toBeTruthy()
    expect(container.textContent).toContain('DOCUMENTS')
    // failed is not published per run, so it is listed as unreported and left out of the bar.
    expect(container.textContent).toMatch(/Failed\s*Not reported/)
    expect(container.textContent).toContain('left out of the total rather than counted as zero')
  })

  it('keeps run age, time on this job and heartbeat recency as three different facts', async () => {
    const run = { ...snapshot.runs[0], started_at: iso(-3600),
      current_job_started_at: iso(-2820), current_job_heartbeat_at: iso(-20) }
    const container = await mount({ nodeId: 's1:assess', node: { kind: 'run', run } })
    expect(container.textContent).toMatch(/RUN ELAPSED\s*1h/)
    expect(container.textContent).toMatch(/ON THIS JOB\s*47m/)
    expect(container.textContent).toMatch(/LAST HEARTBEAT\s*20s ago/)
    expect(container.textContent).toContain('From the claim, which does not move')
    expect(container.textContent).toContain('Lease freshness, not run duration')
  })

  it('says a pre-v16 claim time is unknown instead of reading the heartbeat as a start', async () => {
    const run = { ...snapshot.runs[0], started_at: iso(-3600),
      current_job_started_at: null, current_job_heartbeat_at: iso(-20) }
    const container = await mount({ nodeId: 's1:assess', node: { kind: 'run', run } })
    expect(container.textContent).toContain('Claimed before the claim time was recorded')
    expect(container.textContent).toContain('Not inferred from the heartbeat')
    // The heartbeat is still shown — it is a real reading, just not this one.
    expect(container.textContent).toMatch(/LAST HEARTBEAT\s*20s ago/)
  })

  it('calls out a worker that has stopped checking in while still holding the job', async () => {
    const run = { ...snapshot.runs[0], started_at: iso(-3600),
      current_job_started_at: iso(-2820), current_job_heartbeat_at: iso(-900) }
    const container = await mount({ nodeId: 's1:assess', node: { kind: 'run', run } })
    expect(container.textContent).toContain('Worker has stopped checking in')
    expect(container.textContent).toContain('The job is still claimed, so nothing else can pick it up')
  })

  it('does not cry stale for a heartbeat that is merely a couple of intervals old', async () => {
    const run = { ...snapshot.runs[0], current_job_started_at: iso(-2820),
      current_job_heartbeat_at: iso(-200) }
    const container = await mount({ nodeId: 's1:assess', node: { kind: 'run', run } })
    expect(container.textContent).not.toContain('stopped checking in')
  })

  it('shows the classified failure class and the retries, never the error text', async () => {
    const run = { ...snapshot.runs[0], max_attempts_seen: 3, last_error_class: 'source_rate_limit' }
    const container = await mount({ nodeId: 's1:assess', node: { kind: 'run', run } })
    expect(container.textContent).toContain('Source rate limit')
    expect(container.textContent).toContain('3 attempts')
    expect(container.textContent).toContain('vocabulary term, never the error text')
  })

  it('places the run in its pipeline from the scan’s other stage rows', async () => {
    const runs = [
      { ...snapshot.runs[0] },
      { scan_id: 's1', stage: 'discover', status: 'recent', completed: 20, total: 20,
        source: 'drive', owner: 'operator@example.org' },
    ]
    const container = await mount({ nodeId: 's1:assess', node: runNode,
      snapshot: { ...snapshot, runs } })
    expect(container.textContent).toContain('PIPELINE')
    expect(container.textContent).toContain('Discover')
    expect(container.textContent).toContain('(20/20)')
    expect(container.textContent).toContain('(8/20)')
  })

  it('reports an absent pipeline stage as unreported, never as “not started”', async () => {
    const container = await mount({ nodeId: 's1:assess', node: runNode })
    // Only the assess row exists in the default fixture.
    expect(container.textContent).toContain('Discover, Remediate, Release: Not reported')
    expect(container.textContent).toContain('never “did not run”')
    expect(container.textContent).not.toMatch(/not started/i)
  })

  it('draws SharePoint site coverage when the run checkpointed any', async () => {
    const run = { ...snapshot.runs[0], sites_total: 30, sites_done: 12, sites_unread: 2,
      libraries_total: 61 }
    const container = await mount({ nodeId: 's1:assess', node: { kind: 'run', run } })
    expect(container.querySelector('[aria-label="12 of 30 sites read"]')).toBeTruthy()
    expect(container.textContent).toContain('61 libraries')
    expect(container.textContent).toContain('2 sites not read (blocked or skipped)')
  })

  it('omits site coverage entirely for a run with no site data', async () => {
    const container = await mount({ nodeId: 's1:assess', node: runNode })
    expect(container.textContent).not.toContain('SITE COVERAGE')
    expect(container.textContent).not.toContain('0 of 0 sites')
  })

  const driveNode = { kind: 'source', label: 'Google Drive', source: 'drive', active: 1 }

  it('reports documents, which the snapshot publishes, alongside the run count', async () => {
    const container = await mount({ nodeId: 'source:drive', node: driveNode })
    expect(container.textContent).toContain('DOCUMENTS')
    expect(container.textContent).toContain('8 of 20')
  })

  it('lists classified failures by class and stage, without claiming the connector caused them', async () => {
    const runs = [
      { ...snapshot.runs[0], last_error_class: 'rate_limit', max_attempts_seen: 4 },
      { scan_id: 's9', source: 'drive', stage: 'discover', status: 'active',
        last_error_class: 'auth', max_attempts_seen: 2, completed: 0 },
    ]
    const container = await mount({ nodeId: 'source:drive', node: driveNode,
      snapshot: { ...snapshot, runs } })
    expect(container.textContent).toContain('CLASSIFIED FAILURES')
    // The label map fix: these render as words, not as raw tokens.
    expect(container.textContent).toContain('Rate limited')
    expect(container.textContent).toContain('Authentication failed')
    expect(container.textContent).not.toMatch(/\brate_limit\b/)
    expect(container.textContent).toContain('while assess')
    expect(container.textContent).toContain('up to 4 attempts')
    // And the caption that stops it being read as connector attribution.
    expect(container.textContent).toContain('may be the AI provider rather than this connector')
  })

  it('says nothing has failed rather than showing an empty failures list', async () => {
    const container = await mount({ nodeId: 'source:drive', node: driveNode })
    expect(container.textContent).toContain('No classified failure has been recorded')
    expect(container.textContent).not.toContain('CLASSIFIED FAILURES')
  })

  it('sums site coverage across the connector’s runs, and omits it where there is none', async () => {
    const withSites = [
      { ...snapshot.runs[0], sites_total: 30, sites_done: 12, sites_unread: 2, libraries_total: 61 },
      { scan_id: 's9', source: 'drive', stage: 'discover', status: 'active',
        sites_total: 10, sites_done: 10, sites_unread: 0, libraries_total: 14, completed: 0 },
    ]
    const container = await mount({ nodeId: 'source:drive', node: driveNode,
      snapshot: { ...snapshot, runs: withSites } })
    expect(container.querySelector('[aria-label="22 of 40 sites read across 2 runs"]')).toBeTruthy()
    expect(container.textContent).toContain('75 libraries')
    expect(container.textContent).toContain('2 sites not read (blocked or skipped)')

    // The default fixture has no site data at all.
    const plain = await mount({ nodeId: 'source:drive', node: driveNode })
    expect(plain.textContent).not.toContain('SITE COVERAGE')
  })

  it('lists the runs on the connector, failing first, and names no scan or owner', async () => {
    const runs = [
      { ...snapshot.runs[0] },
      { scan_id: 's9', source: 'drive', stage: 'discover', status: 'active', completed: 0,
        last_error_class: 'auth', owner: 'someone@example.org', updated_at: iso(-30) },
    ]
    const container = await mount({ nodeId: 'source:drive', node: driveNode,
      snapshot: { ...snapshot, runs } })
    const list = container.querySelector('ul[aria-labelledby="source-run-list"]')
    expect(list).toBeTruthy()
    // Lowercase on purpose: the stage is capitalised by CSS, so this is what a screen reader
    // and textContent actually see. Asserting the rendered casing would be asserting the
    // stylesheet.
    expect(list.querySelectorAll('li')[0].textContent).toContain('discover')
    expect(list.querySelectorAll('li')[0].textContent).toContain('Authentication failed')
    // Cross-tenant screen: no scan id, no owner.
    expect(container.textContent).not.toContain('s9')
    expect(container.textContent).not.toMatch(/@example\.org/)
    expect(container.textContent).toContain('never names a scan or its owner')
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

  const outputNode = { kind: 'output', label: 'Durable outputs' }

  it('names the dead-letter count for what it counts, not as a storage failure', async () => {
    const container = await mount({ nodeId: 'infra:output', node: outputNode })
    expect(container.textContent).toContain('DEAD-LETTERED JOBS')
    expect(container.textContent).toContain('Every job type, not only output writes')
    expect(container.textContent).toContain('Deliberate stops excluded')
    // The old heading claimed a subsystem this number says nothing about.
    expect(container.textContent).not.toContain('STORAGE FAILURES')
  })

  it('names a storage-specific count as unavailable, with the reason', async () => {
    const container = await mount({ nodeId: 'infra:output', node: outputNode })
    expect(container.textContent).toMatch(/STORAGE-SPECIFIC FAILURES\s*Not reported/)
    expect(container.textContent).toContain('failure classifier has no storage class')
  })

  it('reports in-flight work as unavailable when neither stage is in the snapshot', async () => {
    const summary = { ...snapshot.summary, by_stage: { assess: { running: 2, queued: 10 } } }
    const container = await mount({ nodeId: 'infra:output', node: outputNode,
      snapshot: { ...snapshot, summary } })
    expect(container.textContent).toMatch(/REMEDIATE AND RELEASE IN FLIGHT\s*Not reported/)
    expect(container.textContent).toContain('Neither stage is reported in this snapshot')
    // The defect: 0 + 0 read as a confident zero.
    expect(container.textContent).not.toMatch(/REMEDIATE AND RELEASE IN FLIGHT\s*0/)
  })

  it('says a partial in-flight count is partial', async () => {
    const summary = { ...snapshot.summary,
      by_stage: { remediate: { completed: 12, running: 1 } } }
    const container = await mount({ nodeId: 'infra:output', node: outputNode,
      snapshot: { ...snapshot, summary } })
    expect(container.textContent).toContain('Only one of the two stages is reported')
  })

  it('draws each output stage bounded against its own published total', async () => {
    const summary = { ...snapshot.summary, by_stage: {
      remediate: { completed: 12, total: 20, running: 1, queued: 2 },
      release: { completed: 9, total: 9, running: 0, queued: 0 },
    } }
    const container = await mount({ nodeId: 'infra:output', node: outputNode,
      snapshot: { ...snapshot, summary } })
    expect(container.textContent).toContain('OUTPUT STAGES')
    expect(container.querySelector('[aria-label="Corrected copies: 60% of 20 documents"]')).toBeTruthy()
    expect(container.querySelector('[aria-label="Verified and released: 100% of 9 documents"]')).toBeTruthy()
    expect(container.textContent).toContain('1 running, 2 waiting')
  })

  it('draws no bar for a stage that published no total', async () => {
    const summary = { ...snapshot.summary, by_stage: { remediate: { completed: 12, running: 1 } } }
    const container = await mount({ nodeId: 'infra:output', node: outputNode,
      snapshot: { ...snapshot, summary } })
    expect(container.textContent).toContain('the completed count is not divided by itself')
    expect(container.querySelector('[aria-label^="Corrected copies:"]')).toBeFalsy()
  })

  it('reports an absent output stage as unreported, not as having produced nothing', async () => {
    const summary = { ...snapshot.summary, by_stage: { remediate: { completed: 12, total: 20 } } }
    const container = await mount({ nodeId: 'infra:output', node: outputNode,
      snapshot: { ...snapshot, summary } })
    expect(container.textContent).toContain('Verified and released: Not reported')
    expect(container.textContent).toContain('never “produced nothing”')
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

describe('Request health panel', () => {
  const ingress = { ...capacity, metrics_window_minutes: 15,
    metrics: { ...capacity.metrics,
      requests: azureMetric('Requests', 'Requests', 40, [[-60, 150], [0, 150]]),
      response_ms: azureMetric('Average response time', 'ResponseTime', 42, [[0, 42]]),
      retries: azureMetric('Request retries', 'ResiliencyRequestRetries', 3, [[0, 3]]),
      connect_timeouts: azureMetric('Connection timeouts', 'ResiliencyConnectTimeouts', null, [], false) },
    status_classes: { '2xx': 280, '4xx': 18, '5xx': 2 } }

  it('shows the ingress counters Azure does report', async () => {
    const container = await mount({ nodeId: 'infra:intake', capacity: ingress,
      node: { kind: 'intake', label: 'ACP intake' } })
    expect(container.textContent).toContain('Request health')
    expect(container.textContent).toContain('REQUEST RATE')
    expect(container.textContent).toContain('20/min')
    expect(container.textContent).toContain('CONNECTION TIMEOUTS')
  })

  it('never shows an average under a percentile label', async () => {
    const container = await mount({ nodeId: 'infra:intake', capacity: ingress,
      node: { kind: 'intake', label: 'ACP intake' } })
    expect(container.textContent).toContain('AVERAGE RESPONSE TIME')
    expect(container.textContent).toContain('An average, not a percentile')
    expect(container.textContent).toContain('not shown rather than approximated from the mean')
    // The caption names P50/P95/P99 as the thing that is missing, so their presence in the text is
    // correct. What must not appear is a percentile with a VALUE beside it.
    expect(container.textContent).toMatch(/P50, P95 and P99 need request-level telemetry/)
    expect(container.textContent).not.toMatch(/P(50|95|99)\s*[:·]?\s*\d/)
  })

  it('says an app with no ingress has none rather than showing zeroes', async () => {
    const container = await mount({ nodeId: 'infra:intake', capacity: { configured: true, metrics: {} },
      node: { kind: 'intake', label: 'ACP intake' } })
    expect(container.textContent).toContain('claim from a queue rather than serving requests')
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

describe('Tracing panel', () => {
  const workerNode = { kind: 'worker', label: 'Assess workers', service }
  const withTracing = (tracing) => ({ ...snapshot, summary: { ...snapshot.summary, tracing } })

  it('says tracing is off and why, rather than offering a dead drill-down', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      snapshot: withTracing({ enabled: false, reason: 'not configured' }) })
    expect(container.textContent).toContain('Traces')
    expect(container.textContent).toContain('Off')
    expect(container.textContent).toContain('Tracing is off — not configured')
    expect(container.textContent).not.toContain('Correlates by')
  })

  it('names what a reader can pivot on when tracing is collecting', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      snapshot: withTracing({ enabled: true, correlation: 'full', sampling_ratio: 1 }) })
    expect(container.textContent).toContain('Collecting')
    expect(container.textContent).toContain('sampling 100%')
    expect(container.textContent).toContain('Correlates by run, batch, job, tenant, document')
  })

  it('says when spans export but tenant and document correlation is not available', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      snapshot: withTracing({ enabled: true, correlation: 'ids_only', sampling_ratio: 0.25 }) })
    expect(container.textContent).toContain('Correlates by run, batch, job')
    expect(container.textContent).not.toContain('tenant, document')
    expect(container.textContent).toContain('ACP_TELEMETRY_SALT is unset')
    expect(container.textContent).toContain('sampling 25%')
  })
})

describe('Event timeline', () => {
  const workerNode = { kind: 'worker', label: 'Assess workers', service }

  it('lists this component events newest first, with time, icon, outcome and correlation', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode })
    const items = [...container.querySelectorAll('[aria-label="Live event timeline"] ol li')]
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
    const items = [...container.querySelectorAll('[aria-label="Live event timeline"] ol li')]
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
  // REWRITTEN, not merely re-pointed: this asserted `container.querySelector('details')`, and the
  // fact wall is now grouped disclosures built from `<button aria-expanded>` — `details`/`summary`
  // is reported inconsistently by screen readers, several announcing no expanded state at all.
  // What the old test was protecting (the facts are still reachable, verbatim, with the
  // never-estimated note) is asserted here; the element it happened to be inside is not.
  const factsPanel = (container) => container.querySelector('[aria-label="Operational facts"]')
  const factButton = (container, title) =>
    [...factsPanel(container).querySelectorAll('button')].find((b) => b.textContent.startsWith(title))

  it('keeps every operational fact reachable, grouped and collapsed', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: { kind: 'worker', label: 'Assess workers', service },
      facts: [['Service health', 'Online'], ['Replica size', '2 vCPU · 4Gi RAM · 8Gi temporary disk']] })
    const panel = factsPanel(container)
    expect(panel.textContent).toContain('Operational facts')
    expect(panel.textContent).toContain('are never estimated')
    // Both groups are offered; neither is open, so the values are hidden rather than absent.
    expect(factButton(container, 'Capacity').getAttribute('aria-expanded')).toBe('false')
    expect(factButton(container, 'Deployment').getAttribute('aria-expanded')).toBe('false')
    expect(panel.querySelector('#facts-capacity').hidden).toBe(true)
    expect(panel.querySelector('#facts-capacity').textContent).toContain('2 vCPU · 4Gi RAM · 8Gi temporary disk')
  })

  it('opens one group at a time and says so in aria-expanded', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: { kind: 'worker', label: 'Assess workers', service },
      facts: [['Service health', 'Online'], ['Replica size', '2 vCPU · 4Gi RAM · 8Gi temporary disk']] })
    const button = factButton(container, 'Capacity')
    expect(button.getAttribute('aria-controls')).toBe('facts-capacity')
    await click(button)
    expect(factButton(container, 'Capacity').getAttribute('aria-expanded')).toBe('true')
    expect(factsPanel(container).querySelector('#facts-capacity').hidden).toBe(false)
    // The other group is untouched by opening this one.
    expect(factButton(container, 'Deployment').getAttribute('aria-expanded')).toBe('false')
    await click(factButton(container, 'Capacity'))
    expect(factButton(container, 'Capacity').getAttribute('aria-expanded')).toBe('false')
  })

  it('shows a fact whose label the group map does not know rather than dropping it', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: { kind: 'worker', label: 'Assess workers', service },
      facts: [['Quantum flux', 'Nominal']] })
    expect(factButton(container, 'Other')).toBeTruthy()
    expect(factsPanel(container).querySelector('#facts-other').textContent).toContain('Quantum flux')
    expect(factsPanel(container).querySelector('#facts-other').textContent).toContain('Nominal')
  })
})

describe('Active alerts panel', () => {
  const workerNode = { kind: 'worker', label: 'Assess workers', service }
  const withAlerts = (alerts) => ({ ...capacity, alerts })
  const rule = (over = {}) => ({
    name: 'assess-cpu-high', severity: 2, severity_label: 'Warning', enabled: true,
    state: 'resolved', since: null, condition: 'Average CpuPercentage GreaterThan 85',
    description: null, window: 'PT5M', frequency: 'PT1M', ...over,
  })
  const panel = (container) =>
    container.querySelector('[aria-label="Active alerts"]')

  it('says "Not monitored" rather than showing a clear panel when no rule watches the service', async () => {
    // The whole reason the panel exists. On screen, not just in the model: a green tick over an
    // unmonitored service answers "is this healthy?" with evidence nobody has.
    const container = await mount({
      nodeId: 'stage:assess', node: workerNode,
      capacity: withAlerts({ queried: true, rules_total: 0, rules_enabled: 0, firing: [], rules: [] }),
    })
    const text = panel(container).textContent
    expect(text).toContain('Not monitored')
    expect(text).toMatch(/No alert rules watch this service/)
    expect(text).not.toMatch(/No alerts firing/)
  })

  it('says "No alerts firing" only when rules actually exist to fire', async () => {
    const container = await mount({
      nodeId: 'stage:assess', node: workerNode,
      capacity: withAlerts({ queried: true, rules_total: 2, rules_enabled: 2, firing: [], rules: [rule(), rule({ name: 'assess-restarts' })] }),
    })
    const text = panel(container).textContent
    expect(text).toContain('No alerts firing')
    expect(text).not.toContain('Not monitored')
  })

  it('shows a firing rule, its severity in words, and when it started', async () => {
    const fired = rule({ name: 'assess-queue-stalled', severity: 0, severity_label: 'Critical',
      state: 'fired', since: iso(-600) })
    const container = await mount({
      nodeId: 'stage:assess', node: workerNode,
      capacity: withAlerts({ queried: true, rules_total: 2, rules_enabled: 2, firing: [fired], rules: [fired, rule()] }),
    })
    const text = panel(container).textContent
    expect(text).toContain('assess-queue-stalled')
    expect(text).toContain('Firing')
    expect(text).toContain('Critical')
    expect(text).toMatch(/Firing since/)
    expect(text).toContain('1 of 2 rules firing.')
  })

  it('renders a rule nobody could read as "Not reported", never as clear', async () => {
    const container = await mount({
      nodeId: 'stage:assess', node: workerNode,
      capacity: withAlerts({ queried: true, rules_total: 1, rules_enabled: 1, firing: [],
        rules: [rule({ state: 'unknown' })] }),
    })
    const text = panel(container).textContent
    expect(text).toContain('Not reported')
    expect(text).not.toMatch(/\bClear\b/)
  })

  it('names the missing Monitoring Reader grant, which is the version an operator can act on', async () => {
    const container = await mount({
      nodeId: 'stage:assess', node: workerNode,
      capacity: withAlerts({ queried: false, rules_total: null, firing: [], rules: [],
        unavailable_reason: 'permission' }),
    })
    expect(panel(container).textContent).toMatch(/Monitoring Reader/)
  })

  it('is unavailable, not clear, when the deployment reports no alerts block at all', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, capacity })
    const text = panel(container).textContent
    expect(text).toContain('Not reported')
    expect(text).not.toContain('No alerts firing')
  })

  it('distinguishes its states without relying on colour', async () => {
    // WCAG 1.4.1. Each state has to be readable with the styles stripped.
    const shapes = []
    for (const alerts of [
      { queried: true, rules_total: 0, rules_enabled: 0, firing: [], rules: [] },
      { queried: true, rules_total: 1, rules_enabled: 1, firing: [], rules: [rule()] },
      { queried: true, rules_total: 1, rules_enabled: 1, firing: [rule({ state: 'fired' })], rules: [rule({ state: 'fired' })] },
      { queried: false, firing: [], rules: [], unavailable_reason: 'error' },
    ]) {
      const container = await mount({ nodeId: 'stage:assess', node: workerNode, capacity: withAlerts(alerts) })
      shapes.push(panel(container).textContent.replace(/\s+/g, ' ').slice(0, 60))
    }
    expect(new Set(shapes).size).toBe(shapes.length)
  })

  it('does not claim an Azure provenance for a reading Azure never gave', async () => {
    const container = await mount({
      nodeId: 'stage:assess', node: workerNode,
      capacity: withAlerts({ queried: false, firing: [], rules: [], unavailable_reason: 'error' }),
    })
    const text = panel(container).textContent
    expect(text).not.toMatch(/Azure Monitor · /)
    // And no age either: "20s ago" beside "Not reported" would date a measurement nobody took.
    expect(text).not.toMatch(/\d+s ago/)
  })

  it('is not shown for a node that has no container app behind it', async () => {
    // A run and a source are not backed by a worker app, so there is no rule set to report and
    // an empty panel there would read as "no alerts" for something never checked.
    for (const node of [
      { kind: 'run', label: 'Run s1', run: snapshot.runs[0] },
      { kind: 'queue', label: 'Shared queue' },
    ]) {
      const container = await mount({ nodeId: 'x', node })
      expect(panel(container)).toBeNull()
    }
  })
})

describe('Azure health panels', () => {
  const workerNode = { kind: 'worker', label: 'Assess workers', service }
  const rhPanel = (c) => c.querySelector('[aria-label="Azure resource health"]')
  const shPanel = (c) => c.querySelector('[aria-label="Azure platform incidents"]')
  const withRh = (resource_health) => ({ ...capacity, resource_health })
  const withSh = (service_health) => ({ ...capacity, service_health })

  it('shows a quiet window as "No health events" and points at the live metrics', async () => {
    // The claim the activity log cannot support is "Available". A quiet window is the healthy
    // case and also what an outage looks like before Azure ingests it.
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: withRh({ queried: true, status: null, transitions: [], window_hours: 24 }) })
    const text = rhPanel(container).textContent
    expect(text).toContain('No health events')
    expect(text).toMatch(/live metrics/)
    expect(text).not.toContain('Available')
  })

  it('dates a reported transition instead of presenting it as now', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: withRh({ queried: true, status: 'Degraded', previous: 'Available',
        cause: 'PlatformInitiated', reported_at: iso(-3600), window_hours: 24,
        transitions: [{ at: iso(-3600), status: 'Degraded', previous: 'Available',
          cause: 'PlatformInitiated', summary: null }] }) })
    const text = rhPanel(container).textContent
    expect(text).toContain('Degraded')
    expect(text).toMatch(/Last reported/)
    expect(text).toMatch(/last reported health transition/)
    expect(text).toMatch(/platform-initiated/)
  })

  it('claims no health at all when the query failed', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: withRh({ queried: false, transitions: [], unavailable_reason: 'permission' }) })
    const text = rhPanel(container).textContent
    expect(text).toContain('Not reported')
    expect(text).toMatch(/Monitoring Reader/)
    expect(text).not.toMatch(/\d+s ago|\d+m ago/)
  })

  it('shows an Azure incident on every node, not just on a worker', async () => {
    // Subscription-wide. A regional incident is context for the whole map; scoping it to one
    // service would read as that service being at fault.
    const sh = { queried: true, window_hours: 24, active: [{ tracking_id: 'ABC-123',
      kind: 'Incident', stage: 'Active', resolved: false, title: 'Networking degradation',
      summary: 'We are investigating.', at: iso(-600),
      services: [{ service: 'Container Apps', regions: ['East US'] }] }] }
    for (const node of [workerNode, { kind: 'queue', label: 'Shared queue' }]) {
      const container = await mount({ nodeId: 'x', node, capacity: withSh(sh) })
      const text = shPanel(container).textContent
      expect(text).toContain('Networking degradation')
      expect(text).toContain('East US')
      expect(text).toContain('ABC-123')
      expect(text).toContain('1 active incident')
    }
  })

  it('keeps a resolved incident visible and marked as resolved', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: withSh({ queried: true, window_hours: 24, active: [{ tracking_id: 'X',
        kind: 'Incident', stage: 'Resolved', resolved: true, title: 'Storage latency',
        summary: null, at: iso(-1200), services: [] }] }) })
    const text = shPanel(container).textContent
    expect(text).toContain('Storage latency')
    expect(text).toContain('Resolved')
    expect(text).not.toContain('active incident')
  })

  it('says no incidents only when it actually asked', async () => {
    const asked = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: withSh({ queried: true, window_hours: 24, active: [] }) })
    expect(shPanel(asked).textContent).toMatch(/No Azure incidents/)

    const failed = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: withSh({ queried: false, active: [], unavailable_reason: 'error' }) })
    expect(shPanel(failed).textContent).not.toMatch(/No Azure incidents/)
  })

  it('is absent entirely when Azure is not configured, but present when a query failed', async () => {
    // The two are different: an attempted query that failed is an actionable gap and has to be
    // visible; a deployment with no Azure at all would otherwise carry a permanent "Not reported"
    // panel on every drawer, which is noise. `unavailable_reason` is set only when a call was made.
    const notConfigured = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: { ...capacity, service_health: { queried: false, active: [] } } })
    expect(shPanel(notConfigured)).toBeNull()

    const queryFailed = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: withSh({ queried: false, active: [], unavailable_reason: 'error' }) })
    expect(shPanel(queryFailed)).not.toBeNull()
  })

  it('renders Microsoft prose as text, never as markup', async () => {
    // The backend strips tags; this asserts the drawer does not reintroduce them by rendering
    // whatever arrives as HTML. The two halves of that control have to hold together.
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: withSh({ queried: true, window_hours: 24, active: [{ tracking_id: 'X',
        kind: 'Incident', stage: 'Active', resolved: false,
        title: '<img src=x onerror=alert(1)>Outage', summary: '<b>bold</b>', at: iso(-60),
        services: [] }] }) })
    // Scoped to the incident LIST, not the panel: the panel's own heading is a <b> of ours.
    const list = shPanel(container).querySelector('ul')
    expect(list.querySelector('img')).toBeNull()
    expect(list.querySelector('b')).toBeNull()
    expect(list.textContent).toContain('<img src=x onerror=alert(1)>Outage')
  })

  it('does not show the resource-health panel for a node with no container app', async () => {
    const container = await mount({ nodeId: 'x', node: { kind: 'queue', label: 'Shared queue' } })
    expect(rhPanel(container)).toBeNull()
  })
})

describe('Deployments panel', () => {
  const workerNode = { kind: 'worker', label: 'Assess workers', service }
  const dPanel = (c) => c.querySelector('[aria-label="Deployment activity"]')
  const gaps = [
    { step: 'Build started', reason: 'Runs in the CI workflow, not in Azure.' },
    { step: 'Image published', reason: 'Happens in the container registry.' },
    { step: 'Smoke test passed', reason: 'Runs in the CI workflow after the rollout.' },
  ]
  const withDeploy = (deployments, revision_comparison = null) =>
    ({ ...capacity, deployments, revision_comparison })
  const base = (over = {}) => ({ queried: true, events: [], window_hours: 24, not_reported: gaps,
    system_logs: { available: false, reason: 'Needs a Log Analytics workspace; lags ~three minutes.' },
    unavailable_reason: null, ...over })

  it('names the steps Azure cannot see, even with an empty timeline', async () => {
    // The point of the panel. An empty timeline that says nothing else claims the deployment
    // started at "revision created" — and a build that never produced an image looks identical
    // to no deployment at all.
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: withDeploy(base()) })
    const text = dPanel(container).textContent
    expect(text).toContain('Build started')
    expect(text).toContain('Image published')
    expect(text).toContain('Smoke test passed')
    expect(text).toMatch(/CI workflow/)
  })

  it('says the system-log feed needs Log Analytics and lags', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: withDeploy(base()) })
    const text = dPanel(container).textContent
    expect(text).toContain('System logs')
    expect(text).toMatch(/Log Analytics/)
  })

  it('shows a failed deployment as failed, not as one more line', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: withDeploy(base({ events: [
        { at: iso(-600), kind: 'operation', label: 'Container app updated', status: 'Failed',
          failed: true, detail: 'ImagePullBackOff: manifest unknown' },
        { at: iso(-900), kind: 'revision', label: 'Revision v2 created', status: 'Provisioned',
          failed: false, detail: 'acr.io/acp:v2' }] })) })
    const text = dPanel(container).textContent
    expect(text).toContain('1 failed')
    expect(text).toContain('ImagePullBackOff')
    expect(text).toContain('Revision v2 created')
  })

  it('marks a timeline partial when Azure’s own operations are missing from it', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: withDeploy(base({ queried: false, unavailable_reason: 'error', events: [
        { at: iso(-900), kind: 'revision', label: 'Revision v2 created', status: 'Provisioned',
          failed: false, detail: null }] })) })
    const text = dPanel(container).textContent
    expect(text).toContain('Partial')
    expect(text).toMatch(/activity-log query failed/)
  })

  it('shows a revision change from and to, and the rollback target', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: withDeploy(base(), {
        current: { name: 'v2', image: 'acr.io/acp:v2' },
        previous: { name: 'v1', image: 'acr.io/acp:v1' },
        changes: [{ field: 'image', label: 'Image', from: 'acr.io/acp:v1', to: 'acr.io/acp:v2' }],
        rollback: { name: 'v1' }, rollback_reason: null,
        not_compared: [{ field: 'cpu_used', label: 'CPU actually used',
          reason: 'Per app, not per revision.' }] }) })
    const text = dPanel(container).textContent
    expect(text).toContain('acr.io/acp:v1 → acr.io/acp:v2')
    expect(text).toContain('Rollback target: v1')
  })

  it('labels the compared CPU as requested and names actual use as not compared', async () => {
    // Two different numbers with the same name. Conflating them makes a resize read as a
    // regression, so the panel has to carry both the label and the caveat.
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: withDeploy(base(), {
        current: { name: 'v2' }, previous: { name: 'v1' },
        changes: [{ field: 'cpu', label: 'CPU requested', from: 1, to: 2 }],
        rollback: null, rollback_reason: 'No earlier revision is still provisioned.',
        not_compared: [{ field: 'cpu_used', label: 'CPU actually used',
          reason: 'Per app, not per revision. The CPU compared above is what the revision requests.' }] }) })
    const text = dPanel(container).textContent
    expect(text).toContain('CPU requested')
    expect(text).toContain('CPU actually used')
    expect(text).toMatch(/not per revision/)
  })

  it('says why there is no rollback target rather than going quiet', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: withDeploy(base(), { current: { name: 'v1' }, previous: null, changes: [],
        rollback: null, rollback_reason: 'No earlier revision is still provisioned.',
        not_compared: [] }) })
    expect(dPanel(container).textContent).toMatch(/No earlier revision is still provisioned/)
  })

  it('is not shown for a node with no container app behind it', async () => {
    const container = await mount({ nodeId: 'x', node: { kind: 'queue', label: 'Shared queue' } })
    expect(dPanel(container)).toBeNull()
  })
})

describe('The seven-section drawer', () => {
  const NODES = [
    ['worker', { kind: 'worker', label: 'Assess workers', service }],
    ['queue', { kind: 'queue', label: 'Shared queue' }],
    ['run', { kind: 'run', label: 'Run s1', run: snapshot.runs[0] }],
    ['source', { kind: 'source', label: 'Google Drive', source: 'drive' }],
    ['output', { kind: 'output', label: 'Corrected copies' }],
    ['intake', { kind: 'intake', label: 'Intake' }],
  ]
  const sections = (container) =>
    [...container.querySelectorAll('h3')].map(h => h.textContent.replace(/^\d+\.\s*/, ''))

  it('opens the SAME seven sections, in the same order, for every node kind', async () => {
    // The PRD's actual requirement. A reader who has learned one node's drawer has learned all of
    // them — which only holds if the shape does not vary by kind.
    const expected = ['Current state', 'Right now', 'Last 15 minutes', 'Live events',
      'Alerts and platform health', 'Configuration and limits',
      'Revision, deployments and traces']
    for (const [name, node] of NODES) {
      const container = await mount({ nodeId: 'x', node })
      expect(sections(container), name).toEqual(expected)
    }
  })

  it('numbers every section 1-7 in DOM order, with no drift between number and position', async () => {
    // Checking only the first and last let a renumbered middle section through: a heading reading
    // "99." in the fourth slot passed, because the ORDER of the headings had not changed. The
    // number is a navigation aid, so a number that disagrees with its position is the bug.
    for (const [name, node] of NODES) {
      const container = await mount({ nodeId: 'x', node })
      const numbers = [...container.querySelectorAll('h3')]
        .map(h => Number(h.textContent.trim().match(/^(\d+)\./)?.[1]))
      expect(numbers, name).toEqual([1, 2, 3, 4, 5, 6, 7])
    }
  })

  it('labels each section for assistive tech with the same number its heading shows', async () => {
    // The visible heading and the aria-label are two renderings of one fact and must not drift.
    const container = await mount({ nodeId: 'stage:assess', node: NODES[0][1] })
    for (const h of container.querySelectorAll('h3')) {
      const text = h.textContent.trim().replace(/\s+/g, ' ')
      expect(container.querySelector(`[aria-label="${text}"]`), text).not.toBeNull()
    }
  })

  it('exposes each section to assistive tech by its number and name', async () => {
    // The headings are visual; the aria-labels are what a screen-reader user navigates by, and
    // "5" alone is not a landmark anybody can find.
    const container = await mount({ nodeId: 'stage:assess', node: NODES[0][1] })
    expect(container.querySelector('[aria-label="5. Alerts and platform health"]')).not.toBeNull()
    expect(container.querySelector('[aria-label="6. Configuration and limits"]')).not.toBeNull()
  })

  it('says why a section is thin rather than dropping it', async () => {
    // An omitted section reads as "nothing to report here", which is a claim — and for a run it
    // would be the wrong one: Azure has plenty to say about the worker the run is executing on.
    for (const kind of ['run', 'queue', 'source', 'output']) {
      const node = NODES.find(([k]) => k === kind)[1]
      const container = await mount({ nodeId: 'x', node })
      const five = container.querySelector('[aria-label="5. Alerts and platform health"]')
      expect(five.textContent, kind).toMatch(/Azure reports no alerts, health or deployments/)
    }
  })

  it('points a run at the worker service that does have the answers', async () => {
    const container = await mount({ nodeId: 'x', node: NODES[2][1] })
    const five = container.querySelector('[aria-label="5. Alerts and platform health"]')
    expect(five.textContent).toMatch(/worker service running it has all three/)
    const six = container.querySelector('[aria-label="6. Configuration and limits"]')
    expect(six.textContent).toMatch(/open one of those/)
  })

  it('shows a worker its real limits, labelled as requested rather than used', async () => {
    // 90% CPU against one core and 90% against four are different situations, and the limit is
    // the half a live metric never shows.
    const container = await mount({ nodeId: 'stage:assess', node: NODES[0][1],
      capacity: { ...capacity, min_replicas: 1, max_replicas: 6,
        cpu_cores_per_replica: 2, memory_per_replica: '4Gi', workload_profile_name: 'D4' } })
    const six = container.querySelector('[aria-label="6. Configuration and limits"]')
    expect(six.textContent).toContain('1 to 6')
    expect(six.textContent).toContain('2 cores')
    expect(six.textContent).toContain('4Gi')
    expect(six.textContent).toContain('D4')
    expect(six.textContent).toMatch(/Requested, not used/)
  })

  it('does not invent a limit the deployment did not report', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: NODES[0][1],
      capacity: { ...capacity, min_replicas: null, max_replicas: null,
        cpu_cores_per_replica: null, memory_per_replica: null, workload_profile_name: null } })
    const six = container.querySelector('[aria-label="6. Configuration and limits"]')
    expect(six.textContent).toContain('Not reported')
    expect(six.textContent).not.toMatch(/\b0 cores\b/)
  })

  it('keeps the live event timeline ahead of the alerts, not buried under them', async () => {
    // Section 4 before 5: what just happened is how an operator orients before reading what is
    // shouting. The old layout put the timeline last, under three Azure panels.
    const container = await mount({ nodeId: 'stage:assess', node: NODES[0][1] })
    const order = sections(container)
    expect(order.indexOf('Live events')).toBeLessThan(order.indexOf('Alerts and platform health'))
  })
})

describe('Capacity cost panel', () => {
  const workerNode = { kind: 'worker', label: 'Assess workers', service }
  const six = (c) => c.querySelector('[aria-label="6. Configuration and limits"]')
  const costFor = (over = {}) => ({ ...capacity, cost: {
    apps: [], basis: 'Estimated from configured capacity', rate_configured: false, currency: null,
    rate_note: 'No rate is configured, so capacity is shown as resource-hours rather than money. '
      + 'Set ACP_COST_VCPU_HOUR and ACP_COST_GIB_HOUR to your own rates.',
    total_vcpu_hours: 6, total_gib_hours: 12, total_floor_vcpu_hours: 2,
    estimated_hourly: null, estimated_daily: null,
    actuals: { available: false, reason: 'Cost Management is not configured for this deployment.',
      billing_note: 'Azure Cost Management refreshes roughly every four hours. Actuals are never live.',
      month_to_date: null, forecast: null, budget_percent: null, last_updated: null },
    not_instrumented: [{ item: 'AI cost per assessment or remediation',
      reason: 'Model spend is not metered per job in ACP.' }], ...over } })

  it('shows resource-hours, not a currency figure, when no rate is configured', async () => {
    // ACP knows exactly how much capacity is provisioned and cannot know what it costs. A made-up
    // price in dollars would be the most confidently wrong number on the screen.
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, capacity: costFor() })
    const text = six(container).textContent
    expect(text).toContain('6 vCPU-h/h')
    expect(text).toContain('12 GiB-h/h')
    expect(text).toMatch(/ACP_COST_VCPU_HOUR/)
    // The MONEY TILE itself must be absent, not merely empty. Asserting only that no currency
    // string appears passed even with the tile forced visible, because an unpriced figure renders
    // as "Not reported" — a tile headed "ESTIMATED PER DAY · Not reported" still implies ACP
    // tried to price it and failed, when in fact it was never asked to.
    expect(text).not.toContain('ESTIMATED PER DAY')
    expect(text).not.toMatch(/\$\d|USD \d/)
  })

  it('never calls any of it live, and says actual spend is not reported', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, capacity: costFor() })
    const text = six(container).textContent
    expect(text).toContain('Estimated from configured capacity')
    expect(text.toLowerCase()).not.toContain('live cost')
    expect(text).toMatch(/Actual spend:.*Not reported/)
    expect(text).toMatch(/every four hours/)
  })

  it('shows money only once the operator has supplied a rate', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: costFor({ rate_configured: true, currency: 'USD', estimated_hourly: 0.288,
        estimated_daily: 6.912, rate_note: null }) })
    const text = six(container).textContent
    expect(text).toContain('USD 6.91')
    expect(text).toMatch(/At your configured rate/)
  })

  it('names the always-on floor as paid for whether or not work arrives', async () => {
    // The one cost figure derivable with no billing access at all, and the one an operator can
    // act on tonight.
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, capacity: costFor() })
    const text = six(container).textContent
    expect(text).toContain('ALWAYS-ON FLOOR')
    expect(text).toMatch(/whether or not work arrives/)
  })

  it('carries the estimate provenance, never the Azure Monitor one', async () => {
    // The measured panels above say "Azure Monitor". This one is derived and must not borrow
    // that label — the distinction is the whole point of the provenance line.
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, capacity: costFor() })
    const text = six(container).textContent
    expect(text).toMatch(/Estimated from configured capacity/)
    // And specifically NOT the measured label. Matching only the line above passed even when the
    // provenance was switched to Azure Monitor, because `basis` says the same words higher up —
    // so this pins the provenance line by what it must never say.
    expect(text).not.toMatch(/Azure Monitor/)
    expect(text).not.toMatch(/\d+[smh] ago/)
  })

  it('names ACP-side spend nobody meters rather than omitting it', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode, capacity: costFor() })
    expect(six(container).textContent).toMatch(/AI cost per assessment/)
  })

  it('appears on every node, because capacity cost is the deployment’s not one node’s', async () => {
    for (const node of [workerNode, { kind: 'queue', label: 'Shared queue' },
      { kind: 'run', label: 'Run s1', run: snapshot.runs[0] }]) {
      const container = await mount({ nodeId: 'x', node, capacity: costFor() })
      expect(six(container).textContent, node.kind).toContain('Capacity cost')
    }
  })
})

describe('Task 19 — worker and queue, as the brief specifies', () => {
  const workerNode = { kind: 'worker', label: 'Assess workers', service }
  const queueNode = { kind: 'queue', label: 'Shared queue' }
  const sec = (c, label) => c.querySelector(`[aria-label="${label}"]`)

  it('caps the gauge at 100% and shows the excess as its own figure', async () => {
    // The brief: "Do not show impossible utilization such as 300% or 2550%. Capacity gauges must
    // be bounded at 100%; show excess work separately as backlog or oversubscription."
    const container = await mount({ nodeId: 'stage:assess',
      node: { kind: 'worker', label: 'Assess workers',
        service: { ...service, active: 51, slots: 2 } } })
    const gauge = sec(container, 'Worker slot utilization')
    expect(gauge.textContent).toContain('100%')
    expect(gauge.textContent).toContain('2 of 2 slots busy')
    expect(gauge.textContent).toContain('49 more jobs running than slots')
    expect(gauge.textContent).not.toMatch(/2550|51 of 2/)
  })

  it('does not contradict itself between the gauge and the slot tile', async () => {
    // Two surfaces, same numbers. The saturation tile used to read "51 of 2 busy" beside a gauge
    // that had already refused to say that.
    const container = await mount({ nodeId: 'stage:assess',
      node: { kind: 'worker', label: 'Assess workers',
        service: { ...service, active: 51, slots: 2 } } })
    expect(container.textContent).not.toMatch(/51 of 2/)
    expect(container.textContent).toMatch(/49 more running than slots/)
  })

  it('calls a connected but silent stream Stale, with the age of what is on screen', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      connection: 'live',
      snapshot: { ...snapshot, generated_at: iso(-240) } })
    const dialog = container.querySelector('[role="dialog"]')
    expect(dialog.textContent).toContain('Stale')
    expect(dialog.textContent).toMatch(/connected but has not delivered a frame/)
  })

  it('keeps the last measurement visible when the stream is unavailable', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      connection: 'unavailable', snapshot: { ...snapshot, generated_at: iso(-600) } })
    const dialog = container.querySelector('[role="dialog"]')
    expect(dialog.textContent).toContain('Unavailable')
    expect(dialog.textContent).toMatch(/last frame that arrived/)
  })

  it('walks the provisioning stages in order for a worker', async () => {
    const container = await mount({ nodeId: 'stage:assess', node: workerNode,
      capacity: { ...capacity, replicas: [
        { name: 'r1', state: 'ready' }, { name: 'r2', state: 'starting' }] } })
    const text = container.querySelector('[aria-label="2. Right now"]').textContent
    expect(text).toContain('Requested')
    expect(text).toContain('Allocating')
    expect(text).toContain('Starting')
    expect(text).toContain('Healthy')
    expect(text).toMatch(/not report when a replica was requested/)
  })

  it('shows the queue arrival, completion and drain estimate', async () => {
    const container = await mount({ nodeId: 'infra:queue', node: queueNode })
    const q = sec(container, 'Shared queue composition')
    expect(q.textContent).toContain('ARRIVING')
    expect(q.textContent).toContain('COMPLETING')
    expect(q.textContent).toContain('ESTIMATED DRAIN')
  })

  it('says a growing queue is not draining rather than inventing a finishing time', async () => {
    const container = await mount({ nodeId: 'infra:queue', node: queueNode,
      snapshot: { ...snapshot, summary: { ...snapshot.summary,
        queue: { ...snapshot.summary.queue, arrived: 600, completed: 60, window_s: 900 } } } })
    const q = sec(container, 'Shared queue composition')
    expect(q.textContent).toContain('Not draining')
    expect(q.textContent).toMatch(/arriving faster than it completes/)
  })

  it('labels the drain estimate as an estimate, never as a measurement', async () => {
    const container = await mount({ nodeId: 'infra:queue', node: queueNode })
    expect(sec(container, 'Shared queue composition').textContent)
      .toMatch(/Estimated from configured capacity/)
  })

  it('renders missing queue rates as Not reported, not as zero', async () => {
    const container = await mount({ nodeId: 'infra:queue', node: queueNode,
      snapshot: { ...snapshot, summary: { ...snapshot.summary,
        queue: { running: 2, waiting: 8, window_s: 900 } } } })
    const q = sec(container, 'Shared queue composition')
    expect(q.textContent).toContain('Not reported')
    expect(q.textContent).not.toMatch(/\b0\/min\b/)
  })

  it('keeps every stream state distinguishable without colour', async () => {
    const seen = []
    for (const [connection, generated_at] of [
      ['live', iso(-3)], ['live', iso(-240)], ['reconnecting', iso(-10)], ['unavailable', iso(-60)],
    ]) {
      const container = await mount({ nodeId: 'stage:assess', node: workerNode, connection,
        snapshot: { ...snapshot, generated_at } })
      seen.push(container.querySelector('[role="dialog"]').textContent.slice(0, 120))
    }
    expect(new Set(seen).size).toBe(4)
  })
})

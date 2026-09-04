/**
 * The Live Operations drawer's derivations, with the honesty invariant as the thing under test:
 * a measurement ACP does not have must come back null and must never be substituted with a zero,
 * an average, or a line drawn through a single sample.
 */
import { describe, expect, it } from 'vitest'
import {
  CAPACITY_RULES, NOT_REPORTED, TREND_WINDOW_MS, appendSample, arcPath, capacityMatchesService,
  chartModel, componentState, defaultMetricFor, deriveEvents, etaSeconds, eventClock,
  eventsForNode, filterEvents, formatDuration, gaugeModel, mergeEvents, metricsForKind,
  PROVENANCE, metricGroups, niceCeiling, num, outputModel, provenance, queueModel, rateSeries,
  replicaLifecycle, reported, revisionLabel, runModel, sampleForNode, saturationModel, secondsSince,
  seriesForMetric, sourceModel, tenantConcentration, trendMarkers, updatedAgo,
} from './liveOpsDrawer.js'

const NOW = Date.parse('2026-09-04T14:32:00Z')
const iso = (offsetS) => new Date(NOW + offsetS * 1000).toISOString()

const service = { role: 'assess', stage: 'assess', active: 2, slots: 3, available: 1, alive: true, age_s: 4, version: 'v25' }
const capacity = {
  configured: true, worker_app_name: 'acp-assess', current_replicas: 2, metrics_available: true,
  cpu_percent: 54, memory_percent: 67, active_revision_name: 'acp-assess--v25',
  revision_provisioning_state: 'Provisioned',
}

describe('Missing measurements stay missing', () => {
  it('never turns an absent value into a number', () => {
    expect(num(undefined)).toBe(null)
    expect(num(null)).toBe(null)
    expect(num('')).toBe(null)
    expect(num('not a number')).toBe(null)
    expect(num(0)).toBe(0)
    expect(reported(null, '%')).toBe(NOT_REPORTED)
    expect(reported(0, '%')).toBe('0%')
  })

  it('says the update time is unknown rather than reporting zero seconds ago', () => {
    expect(updatedAgo(null, NOW)).toBe('Update time unavailable')
    expect(updatedAgo('nonsense', NOW)).toBe('Update time unavailable')
    expect(updatedAgo(iso(-3), NOW)).toBe('Updated 3s ago')
  })

  it('reports a worker gauge as unavailable when slots are not published', () => {
    const gauge = gaugeModel({ alive: true, active: 1, slots: null })
    expect(gauge.available).toBe(false)
    expect(gauge.reason).toMatch(/not reported/i)
  })

  it('leaves the per-run failure count unreported, because the snapshot does not carry one', () => {
    const model = runModel({ completed: 8, total: 20, running: 2, queued: 10 }, [], { nowMs: NOW })
    expect(model.failed).toBe(null)
    expect(model.pct).toBe(40)
  })

  it('reports queue rows it was not given rather than filling them with zero', () => {
    const model = queueModel({ queued: 10, running: 2 }, { nowMs: NOW })
    expect(model.partial).toBe(true)
    expect(model.rows.find((row) => row.key === 'retrying').count).toBe(null)
    expect(model.rows.find((row) => row.key === 'failed').count).toBe(null)
    // The one count an older snapshot DOES publish is shown, as waiting, not split by guesswork.
    expect(model.rows.find((row) => row.key === 'waiting').count).toBe(10)
    expect(model.arrivalPerMin).toBe(null)
    expect(model.completionPerMin).toBe(null)
  })
})

describe('Component state is a shape and a word, not a colour', () => {
  const ctx = { snapshot: { summary: {} }, capacity, connection: 'live' }

  it('separates healthy idle from an outage', () => {
    const idle = componentState({ kind: 'worker', service: { ...service, active: 0 } }, ctx)
    expect(idle.key).toBe('idle')
    expect(idle.detail).toMatch(/healthy, not stalled/)
    const offline = componentState({ kind: 'worker', service: { ...service, alive: false } }, ctx)
    expect(offline.key).toBe('offline')
    expect(offline.icon).not.toBe(idle.icon)
  })

  it('calls a live service with a stale heartbeat degraded, not online', () => {
    expect(componentState({ kind: 'worker', service: { ...service, age_s: 400 } }, ctx).key).toBe('degraded')
  })

  it('distinguishes a stalled queue from one merely at capacity', () => {
    const stalled = componentState({ kind: 'queue' }, { snapshot: { summary: { queued: 4, pressure: 'stalled' } } })
    const saturated = componentState({ kind: 'queue' }, { snapshot: { summary: { queued: 4, pressure: 'saturated' } } })
    expect([stalled.label, saturated.label]).toEqual(['Stalled', 'At capacity'])
    expect(stalled.icon).not.toBe(saturated.icon)
  })

  it('reads intake health from the live stream, including the failure states', () => {
    const state = (connection) => componentState({ kind: 'intake' }, { snapshot: {}, connection }).key
    expect([state('live'), state('reconnecting'), state('unavailable')]).toEqual(['online', 'degraded', 'offline'])
  })
})

describe('Worker gauge thresholds come from a documented rule', () => {
  it('bands on the stated fractions rather than a chosen colour range', () => {
    expect(CAPACITY_RULES).toEqual({ approachingAt: 0.75, saturatedAt: 1 })
    expect(gaugeModel({ ...service, active: 0, slots: 4 }).state).toBe('idle')
    expect(gaugeModel({ ...service, active: 2, slots: 4 }).state).toBe('available')
    expect(gaugeModel({ ...service, active: 3, slots: 4 }).state).toBe('approaching')
    expect(gaugeModel({ ...service, active: 4, slots: 4 }).state).toBe('saturated')
  })

  it('treats a stalled queue as saturation however few slots are busy', () => {
    expect(gaugeModel({ ...service, active: 0, slots: 4 }, { stalled: true }).state).toBe('saturated')
  })

  it('carries the accessible text equivalent the visual gauge cannot', () => {
    expect(gaugeModel({ ...service, active: 2, slots: 3 }).text)
      .toBe('2 of 3 worker slots active (67%), 1 available')
  })

  it('draws a half circle that starts at the left and grows clockwise', () => {
    expect(arcPath(100, 100, 78, 0)).toContain('M 22.00 100.00')
    expect(arcPath(100, 100, 78, 1)).toContain('A 78 78 0 0 1 178.00 100.00')
    // Half of the semicircle is the top of the arc.
    expect(arcPath(100, 100, 78, 0.5)).toContain('100.00 22.00')
  })
})

describe('Queue composition splits waiting from retrying', () => {
  const summary = {
    queued: 12, running: 3, waiting_users: 4, scheduling_policy: 'tenant_fair_least_loaded',
    queue: { running: 3, waiting: 9, retrying: 3, failed: 2, arrived: 30, completed: 45,
      window_s: 900, oldest_queued_at: iso(-125) },
  }

  it('counts every reported state and derives the two rates from the window it was given', () => {
    const model = queueModel(summary, { nowMs: NOW })
    expect(model.segments.map((s) => [s.key, s.count]))
      .toEqual([['running', 3], ['waiting', 9], ['retrying', 3], ['failed', 2]])
    expect(model.total).toBe(17)
    expect(model.partial).toBe(false)
    expect(model.arrivalPerMin).toBe(2)
    expect(model.completionPerMin).toBe(3)
  })

  it('derives the oldest wait from the instant, so the stream can still emit only on change', () => {
    expect(queueModel(summary, { nowMs: NOW }).oldestWaitS).toBe(125)
    expect(formatDuration(125)).toBe('2m 5s')
  })

  it('warns only when one tenant really dominates the waiting work', () => {
    expect(tenantConcentration([{ owner: 'a', queued: 8 }, { owner: 'b', queued: 2 }]))
      .toMatchObject({ owner: 'a', pct: 80, total: 10, concentrated: true })
    expect(tenantConcentration([{ owner: 'a', queued: 5 }, { owner: 'b', queued: 5 }]).concentrated).toBe(false)
    // One waiting job is 100% of the queue and is not a concentration problem.
    expect(tenantConcentration([{ owner: 'a', queued: 1 }]).concentrated).toBe(false)
  })
})

describe('Remaining time is offered only when the samples can carry one', () => {
  const samples = (points) => points.map(([offsetS, completed]) => ({ at: iso(offsetS), completed }))

  it('refuses an estimate from a single sample', () => {
    expect(etaSeconds(samples([[-60, 4]]), 16)).toBe(null)
  })

  it('refuses an estimate from a span too short to be a rate', () => {
    expect(etaSeconds(samples([[-4, 4], [0, 5]]), 16)).toBe(null)
  })

  it('refuses an estimate when nothing has completed over the span', () => {
    expect(etaSeconds(samples([[-120, 4], [0, 4]]), 16)).toBe(null)
  })

  it('estimates from the run own completion rate once there is evidence', () => {
    // 8 documents in 120s = 1 every 15s; 16 left → 240s.
    expect(etaSeconds(samples([[-120, 4], [0, 12]]), 16)).toBe(240)
  })

  it('says nothing rather than infinity when the total is unknown', () => {
    expect(runModel({ completed: 5, running: 1 }, samples([[-120, 1], [0, 5]]), { nowMs: NOW }).eta).toBe(null)
  })
})

describe('The fifteen-minute trend keeps only what it measured', () => {
  it('drops samples older than the window', () => {
    let series = []
    series = appendSample(series, { at: iso(-1200), active_jobs: 1 }, { nowMs: NOW })
    series = appendSample(series, { at: iso(-60), active_jobs: 2 }, { nowMs: NOW })
    expect(series).toHaveLength(1)
    expect(series[0].active_jobs).toBe(2)
    expect(TREND_WINDOW_MS).toBe(900000)
  })

  it('collapses an unchanged reading onto the newest timestamp instead of stacking duplicates', () => {
    let series = []
    for (const offset of [-30, -20, -10]) series = appendSample(series, { at: iso(offset), active_jobs: 2 }, { nowMs: NOW })
    expect(series).toHaveLength(1)
    expect(series[0].at).toBe(iso(-10))
  })

  it('refuses to draw a line through fewer than two real values', () => {
    const one = chartModel([{ at: iso(-30), active_jobs: 3 }], 'active_jobs', { nowMs: NOW })
    expect(one.insufficient).toBe(true)
    expect(one.segments).toEqual([])
    expect(one.sampleCount).toBe(1)
    const none = chartModel([{ at: iso(-30), active_jobs: null }], 'active_jobs', { nowMs: NOW })
    expect(none.sampleCount).toBe(0)
    expect(none.currentLabel).toBe(NOT_REPORTED)
  })

  it('breaks the line at a gap rather than interpolating across it', () => {
    const chart = chartModel([
      { at: iso(-240), active_jobs: 1 }, { at: iso(-180), active_jobs: 2 },
      { at: iso(-120), active_jobs: null },
      { at: iso(-60), active_jobs: 4 }, { at: iso(0), active_jobs: 5 },
    ], 'active_jobs', { nowMs: NOW })
    expect(chart.segments).toHaveLength(2)
    expect(chart.current).toBe(5)
  })

  it('labels both axes and the current value', () => {
    const chart = chartModel([{ at: iso(-120), queue_depth: 3 }, { at: iso(0), queue_depth: 7 }],
      'queue_depth', { nowMs: NOW })
    expect(chart.axis).toMatchObject({ yTop: '10', yZero: '0', xStart: '15 min ago', xEnd: 'now' })
    expect(chart.currentLabel).toBe('7')
  })

  it('turns a cumulative counter into a rate, with no rate for the first point or a reset', () => {
    const points = [
      { t: 0, value: 10 }, { t: 60000, value: 16 }, { t: 120000, value: 4 }, { t: 180000, value: 9 },
    ]
    expect(rateSeries(points).map((p) => p.value)).toEqual([null, 6, null, 5])
  })

  it('rounds the axis to a readable ceiling', () => {
    expect([niceCeiling(0), niceCeiling(3), niceCeiling(7), niceCeiling(42), niceCeiling(null)])
      .toEqual([1, 5, 10, 50, null])
  })

  it('defaults each node to the metric that describes it', () => {
    expect(defaultMetricFor('worker')).toBe('active_jobs')
    expect(defaultMetricFor('queue')).toBe('queue_depth')
    expect(defaultMetricFor('run')).toBe('throughput')
    expect(metricsForKind('worker').map((m) => m.key))
      .toEqual(['active_jobs', 'queue_depth', 'throughput', 'cpu', 'memory', 'replicas',
        'cpu_cores', 'working_set', 'restarts', 'network_in', 'network_out'])
  })

  it('keeps a two-second ACP reading and a one-minute Azure sample in separate groups', () => {
    // Rendered side by side in one picker they read as the same kind of fact; they are not, and
    // the difference is exactly what the provenance line exists to state.
    expect(metricGroups('worker').map((group) => [group.label, group.metrics.length]))
      .toEqual([['ACP live', 3], ['Azure Monitor', 8]])
  })

  it('offers request health on intake, where the requests actually arrive', () => {
    // The workers claim from a queue rather than serving requests, so ingress metrics on a worker
    // node would be a permanent row of zeroes.
    const intake = metricsForKind('intake').map((m) => m.key)
    expect(intake).toContain('requests')
    expect(intake).toContain('response_ms')
    expect(metricsForKind('worker')).not.toContain('requests')
  })
})

describe('Azure Monitor history is preferred over what this tab happened to see', () => {
  const capacity = { worker_app_name: 'acp-assess', measured_at: iso(-20), metrics: {
    cpu_percent: { available: true, latest: 54, average: 47,
      series: [{ at: iso(-120), value: 40 }, { at: iso(-60), value: 47 }, { at: iso(0), value: 54 }] },
    restarts: { available: false, latest: null, series: [] },
  } }
  const observed = [{ at: iso(-30), cpu_pct: 51 }]

  it('charts Azure own fifteen minutes rather than the minute this tab has been open', () => {
    const picked = seriesForMetric(observed, 'cpu', { capacity, service })
    expect(picked.source).toBe('azure')
    expect(picked.samples.map((sample) => sample.cpu_pct)).toEqual([40, 47, 54])
    expect(picked.measuredAt).toBe(iso(-20))
  })

  it('refuses another container app history for a service it does not describe', () => {
    const picked = seriesForMetric(observed, 'cpu', { capacity, service: { role: 'discovery' } })
    expect(picked).toEqual({ samples: [], source: 'unavailable' })
  })

  it('reports an Azure metric with no data as Azure having none, not as no such metric', () => {
    expect(seriesForMetric(observed, 'restarts', { capacity, service })).toEqual({ samples: [], source: 'azure' })
    expect(seriesForMetric(observed, 'network_in', { capacity, service })).toEqual({ samples: [], source: 'unavailable' })
  })

  it('leaves an ACP-measured trend on what this session observed', () => {
    expect(seriesForMetric(observed, 'active_jobs', { capacity, service }))
      .toEqual({ samples: observed, source: 'live' })
  })

  it('prefers the newest one-minute sample over the window average for "right now"', () => {
    const snapshot = { generated_at: iso(0), summary: { by_stage: { assess: { queued: 2, completed: 9 } } } }
    const sample = sampleForNode({ kind: 'worker', service }, { snapshot, capacity })
    expect(sample.cpu_pct).toBe(54)      // latest, not the 47 average
    expect(sample.restarts).toBe(null)   // reported unavailable stays unavailable
  })

  it('falls back to the flat average for a backend that publishes no metrics block', () => {
    const older = { worker_app_name: 'acp-assess', metrics_available: true, cpu_percent: 33, memory_percent: 44 }
    const snapshot = { generated_at: iso(0), summary: { by_stage: {} } }
    const sample = sampleForNode({ kind: 'worker', service }, { snapshot, capacity: older })
    expect(sample.cpu_pct).toBe(33)
    expect(sample.memory_pct).toBe(44)
  })
})

describe('Every value says where it came from and how stale it is', () => {
  it('states the source and the age together', () => {
    expect(provenance('live', { at: iso(-2), nowMs: NOW }).text).toBe('Live · ACP event stream · 2s ago')
    expect(provenance('azure', { at: iso(-20), nowMs: NOW }).text)
      .toBe('Azure Monitor · 1 min interval · 20s ago')
  })

  it('does not imply an age it cannot compute', () => {
    // A source with no timestamp says what it is and stops, rather than reading as "just now".
    expect(provenance('estimate').text).toBe('Estimated from configured capacity · derived, not measured')
    expect(provenance('estimate').ageS).toBe(null)
  })

  it('names an estimate as an estimate and billing as billing', () => {
    expect(PROVENANCE.estimate.detail).toMatch(/not measured/)
    expect(PROVENANCE.billing.detail).toMatch(/not live/)
    expect(provenance('nonsense').label).toBe('Not reported')
  })
})

describe('One container app reading is not charted as another service utilization', () => {
  it('matches only the service whose app Azure actually measured', () => {
    expect(capacityMatchesService(capacity, service)).toBe(true)
    expect(capacityMatchesService(capacity, { role: 'discovery' })).toBe(false)
    expect(capacityMatchesService({ worker_app_name: 'acp-worker' }, service)).toBe(false)
    expect(capacityMatchesService(null, service)).toBe(false)
  })

  it('samples CPU, memory and replicas only for the measured service', () => {
    const snapshot = { generated_at: iso(0), summary: { by_stage: { assess: { queued: 4, completed: 12 } } } }
    const mine = sampleForNode({ kind: 'worker', service }, { snapshot, capacity })
    expect(mine).toMatchObject({ active_jobs: 2, queue_depth: 4, cpu_pct: 54, memory_pct: 67, replicas: 2 })
    const other = sampleForNode({ kind: 'worker', service: { ...service, role: 'discovery', stage: 'discover' } },
      { snapshot, capacity })
    expect(other.cpu_pct).toBe(null)
    expect(other.memory_pct).toBe(null)
    expect(other.replicas).toBe(null)
  })

  it('shows the heartbeat version as the revision when the measured app is a different service', () => {
    expect(revisionLabel({ kind: 'worker', service }, capacity)).toBe('acp-assess--v25')
    expect(revisionLabel({ kind: 'worker', service: { ...service, role: 'discovery' } }, capacity)).toBe('v25')
    expect(revisionLabel({ kind: 'worker', service: { role: 'discovery' } }, null)).toBe(NOT_REPORTED)
  })
})

describe('Events are derived from observed change, and say nothing they did not observe', () => {
  const base = (overrides = {}) => ({
    connection: 'live',
    capacity: { worker_app_name: 'acp-assess', current_replicas: 2, active_revision_name: 'v25' },
    snapshot: {
      generated_at: iso(0),
      runs: [{ scan_id: 's1', stage: 'assess', source: 'drive', owner: 'a@example.org',
        completed: 4, total: 20, running: 2, queued: 8, status: 'active', current_file: 'Report.docx' }],
      summary: { pressure: 'busy', queue: { failed: 0 }, worker_roles: { assess: { alive: true, pool_size: 3, version: 'v25' } } },
    },
    ...overrides,
  })

  it('produces nothing without a previous snapshot to compare against', () => {
    expect(deriveEvents(null, base())).toEqual([])
  })

  it('reports completed work, the claimed file, and the durable write', () => {
    const next = base()
    next.snapshot.runs = [{ ...next.snapshot.runs[0], completed: 6, current_file: 'Mediation Record 11.13.2022.xlsx' }]
    const events = deriveEvents(base(), next, { nowIso: iso(0) })
    const texts = events.map((event) => event.text)
    expect(texts).toContain('2 documents completed')
    expect(texts).toContain('2 results stored')
    expect(texts).toContain('Worker claimed Mediation Record 11.13.2022.xlsx')
    expect(events.every((event) => event.correlation === 's1')).toBe(true)
    expect(events.find((e) => e.text === '2 results stored').nodes).toContain('infra:output')
  })

  it('reports capacity, deployment and failure changes with the right severity', () => {
    const next = base()
    next.snapshot.summary.pressure = 'healthy'
    next.snapshot.summary.queue.failed = 3
    next.snapshot.summary.worker_roles.assess = { alive: true, pool_size: 5, version: 'v26' }
    next.capacity = { worker_app_name: 'acp-assess', current_replicas: 4, active_revision_name: 'v26' }
    const events = deriveEvents(base(), next, { nowIso: iso(0) })
    const byKind = (kind) => events.filter((event) => event.kind === kind).map((event) => event.text)
    expect(byKind('capacity')).toContain('Queue returned below capacity')
    expect(byKind('capacity')).toContain('assess worker slots changed from 3 to 5')
    expect(byKind('deployment')).toContain('assess worker service now running v26')
    expect(byKind('deployment')).toContain('Active revision is now v26')
    expect(byKind('error')).toContain('3 jobs dead-lettered')
  })

  it('treats a lost heartbeat as a warning, not as a scaling event', () => {
    const next = base()
    next.snapshot.summary.worker_roles.assess = { alive: false, pool_size: 3, version: 'v25' }
    const event = deriveEvents(base(), next, { nowIso: iso(0) })
      .find((e) => e.text.includes('stopped reporting'))
    expect(event.kind).toBe('warning')
  })

  it('keeps the newest first, deduped, and bounded', () => {
    const one = { id: 'a', at: iso(-10), kind: 'activity', text: 'first' }
    const two = { id: 'b', at: iso(0), kind: 'capacity', text: 'second' }
    const log = mergeEvents(mergeEvents([], [one]), [two])
    expect(log.map((event) => event.id)).toEqual(['b', 'a'])
    expect(mergeEvents(log, [two])).toHaveLength(2)
    expect(mergeEvents([], Array.from({ length: 300 }, (_, i) => ({ id: `e${i}` })))).toHaveLength(200)
  })

  it('scopes events to the selected component and to the chosen filter', () => {
    const log = [
      { id: '1', kind: 'activity', nodes: ['stage:assess'] },
      { id: '2', kind: 'capacity', nodes: ['infra:queue'] },
      { id: '3', kind: 'error', nodes: ['stage:assess'] },
    ]
    expect(eventsForNode(log, 'stage:assess').map((e) => e.id)).toEqual(['1', '3'])
    expect(filterEvents(log, 'error').map((e) => e.id)).toEqual(['3'])
    expect(filterEvents(log, 'all')).toHaveLength(3)
  })

  it('marks deployment and scaling moments on the timeline, and nothing else', () => {
    const log = [
      { id: '1', kind: 'deployment', at: iso(-60), text: 'deployed' },
      { id: '2', kind: 'activity', at: iso(-30), text: 'completed' },
      { id: '3', kind: 'capacity', at: iso(-3000), text: 'too old' },
    ]
    const markers = trendMarkers(log, { start: NOW - TREND_WINDOW_MS, end: NOW })
    expect(markers.map((m) => m.id)).toEqual(['1'])
  })

  it('formats a wall clock timestamp for each event', () => {
    expect(eventClock('nonsense')).toBe('--:--:--')
    expect(eventClock(iso(0))).toMatch(/^\d{2}:\d{2}:\d{2}$/)
  })
})

describe('Source and output panels name what they cannot measure', () => {
  const snapshot = {
    runs: [
      { scan_id: 's1', source: 'drive', status: 'active', updated_at: iso(-30), completed: 4 },
      { scan_id: 's2', source: 'drive', status: 'recent', updated_at: iso(-90), completed: 9 },
      { scan_id: 's3', source: 'sharepoint', status: 'active', updated_at: iso(-5), completed: 1 },
    ],
    summary: { by_stage: { remediate: { completed: 12, running: 2 }, release: { completed: 9, running: 1 } },
      queue: { failed: 1 } },
  }

  it('counts a connector own runs and names the three facts it does not publish', () => {
    const model = sourceModel({ kind: 'source', source: 'drive' }, snapshot)
    expect(model).toMatchObject({ activeRuns: 1, recentRuns: 1, requestsPerMin: null, throttling: null })
    expect(model.unavailable).toEqual(['Requests per minute', 'Recent throttling', 'Authentication freshness'])
  })

  it('reports output counts it has and refuses a total size Azure did not give', () => {
    expect(outputModel(snapshot)).toMatchObject({
      correctedCopies: 12, verified: 9, awaitingWrite: 3, storageFailures: 1, totalSize: null,
    })
  })

  it('measures elapsed time from an instant, and gives up on a malformed one', () => {
    expect(secondsSince(iso(-90), NOW)).toBe(90)
    expect(secondsSince(null, NOW)).toBe(null)
    expect(secondsSince('nonsense', NOW)).toBe(null)
  })
})


describe('Worker saturation keeps ACP slots and Azure replicas apart', () => {
  const cap = (over = {}) => ({ configured: true, worker_app_name: 'acp-assess', measured_at: iso(-20),
    min_replicas: 1, max_replicas: 4, current_replicas: 2,
    metrics: { replicas: { available: true, latest: 3, series: [] } }, ...over })
  const done = (points) => points.map(([offsetS, completed]) => ({ at: iso(offsetS), completed }))

  it('reports the two capacities separately, because they are opposite problems', () => {
    // Every slot busy with replicas to spare, and every replica up with slots idle, look identical
    // once the two are added together — and call for opposite responses.
    const model = saturationModel({ ...service, active: 3, slots: 3, available: 0 }, cap(),
      { samples: [], queueDepth: 5 })
    expect(model.slots).toEqual({ active: 3, total: 3, available: 0 })
    expect(model.replicas).toMatchObject({ running: 3, min: 1, max: 4, headroom: 1, atMax: false, source: 'azure' })
  })

  it('prefers the Azure replica metric over the control-plane count', () => {
    expect(saturationModel(service, cap()).replicas.running).toBe(3)   // metric latest, not current_replicas
    const noMetric = saturationModel(service, cap({ metrics: {} }))
    expect(noMetric.replicas.running).toBe(2)                          // falls back to current_replicas
  })

  it('says a service is at its scale ceiling rather than implying room', () => {
    const model = saturationModel(service, cap({ metrics: { replicas: { available: true, latest: 4 } } }))
    expect(model.replicas).toMatchObject({ running: 4, headroom: 0, atMax: true })
  })

  it('refuses to call a limit headroom when the running count is unmeasured', () => {
    const model = saturationModel(service, cap({ current_replicas: null, metrics: {} }))
    expect(model.replicas.running).toBe(null)
    expect(model.replicas.headroom).toBe(null)      // max alone is a limit, not spare capacity
    expect(model.replicas.atMax).toBe(false)
  })

  it('reports nothing about replicas for a service Azure did not measure', () => {
    const model = saturationModel({ ...service, role: 'discovery' }, cap())
    expect(model.replicas).toMatchObject({ running: null, min: null, max: null, source: 'unavailable' })
  })

  it('measures the drain from this service own completions', () => {
    // 8 completed over 120s = 1 every 15s; 10 waiting → 150s.
    const model = saturationModel(service, cap(), { samples: done([[-120, 4], [0, 12]]), queueDepth: 10 })
    expect(model.drainSeconds).toBe(150)
    expect(model.drainReason).toBe(null)
  })

  it('refuses a drain time it cannot measure, and says why', () => {
    // The number an operator would use to decide NOT to scale, so a made-up one is worse than none.
    const stalled = saturationModel(service, cap(), { samples: done([[-120, 4], [0, 4]]), queueDepth: 10 })
    expect(stalled.drainSeconds).toBe(null)
    expect(stalled.drainReason).toMatch(/30s of samples with completions/)
    const unknown = saturationModel(service, cap(), { samples: done([[-120, 4], [0, 12]]), queueDepth: null })
    expect(unknown.drainSeconds).toBe(null)
    expect(unknown.drainReason).toMatch(/Queue depth is not reported/)
  })

  it('calls an empty queue clear rather than unmeasurable', () => {
    const model = saturationModel(service, cap(), { samples: [], queueDepth: 0 })
    expect(model.drainSeconds).toBe(0)
    expect(model.drainReason).toBe(null)
  })
})

describe('Replica lifecycle is scoped to the service Azure measured', () => {
  const capacity = { configured: true, worker_app_name: 'acp-assess',
    replicas: [{ name: 'r1', state: 'ready' }],
    revisions: [{ name: 'acp-assess--v25', active: true, provisioning_state: 'Provisioned', traffic_percent: 100 }],
    replica_lifecycle: { counts: { ready: 1, starting: 0, allocating: 0, not_running: 0, draining: 0, unknown: 0 },
      total: 1, unreported_states: ['requested', 'failed'], unreported_reason: 'because Azure does not list them' } }

  it('orders the counts as a rollout reads and carries the unreported states', () => {
    const model = replicaLifecycle(capacity, service)
    expect(model.available).toBe(true)
    expect(model.counts.map((row) => row.state))
      .toEqual(['ready', 'starting', 'allocating', 'draining', 'not_running', 'unknown'])
    expect(model.unreported).toEqual(['requested', 'failed'])
    expect(model.active.name).toBe('acp-assess--v25')
    expect(model.blocked).toBe(null)
  })

  it('surfaces a revision that is not Provisioned as the blocker it is', () => {
    const failed = { ...capacity, revisions: [{ name: 'v26', active: true, provisioning_state: 'Failed',
      provisioning_error: 'ImagePullFailure', age_s: 240 }] }
    expect(replicaLifecycle(failed, service).blocked)
      .toEqual({ state: 'Failed', error: 'ImagePullFailure', ageS: 240 })
  })

  it('declines for a service the measured app does not describe, and when Azure is unconfigured', () => {
    expect(replicaLifecycle(capacity, { role: 'discovery' }).available).toBe(false)
    expect(replicaLifecycle(capacity, { role: 'discovery' }).reason).toMatch(/not this service/)
    expect(replicaLifecycle({ configured: false }, service).reason).toMatch(/not configured/)
  })
})

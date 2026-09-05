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
  PROVENANCE, capacityForService, fairnessModel, metricGroups, niceCeiling, num, outputModel,
  provenance, queueModel, rateSeries,
  LATENCY_PERCENTILES_NOTE, replicaLifecycle, reported, requestHealth, revisionLabel, runModel,
  sampleForNode, saturationModel, scaleEvents, tracingModel,
  scaleExplanation, secondsSince, seriesForMetric, sourceModel, tenantConcentration, throughputModel,
  trendMarkers, updatedAgo, workerJobHealth,
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

  it('withholds a percentage when more work is in flight than there are slots', () => {
    // Seen against a real deployment: "51 of 2 worker slots active (2550%)". `active` counts
    // running jobs across the whole service while `slots` is the pool size from a heartbeat that
    // is last-writer-wins across replicas, so the two are not a ratio — and a stale lease produces
    // the same shape. The condition is named instead of dressed up as 2550% of capacity.
    const gauge = gaugeModel({ ...service, active: 51, slots: 2 })
    expect(gauge.pct).toBe(null)
    expect(gauge.overCommitted).toBe(true)
    expect(gauge.state).toBe('saturated')
    expect(gauge.stateLabel).toBe('Over committed')
    expect(gauge.text).toBe('51 jobs in flight against 2 reported worker slots')
    expect(gauge.text).not.toContain('%')
    expect(gauge.fraction).toBe(1)          // the arc fills, it does not wrap
    expect(gauge.overCommittedNote).toMatch(/last-writer-wins across replicas/)
  })

  it('still reports a real percentage when the counts are comparable', () => {
    const gauge = gaugeModel({ ...service, active: 2, slots: 3 })
    expect(gauge.overCommitted).toBe(false)
    expect(gauge.pct).toBe(67)
    expect(gauge.overCommittedNote).toBe(null)
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


describe('Why Azure has not scaled, answered from the configuration', () => {
  const scale = (over = {}) => ({ min_replicas: 1, max_replicas: 4, polling_interval_s: 30,
    cooldown_period_s: 300, rules_reported: true,
    rules: [{ name: 'queue-depth', type: 'azure-servicebus', metadata: { queueLength: '5' } }],
    attribution: 'Azure Container Apps does not report which scale rule caused a given change; '
      + 'the rules below are the ones that could be responsible.', ...over })
  const counts = (over = {}) => ['ready', 'starting', 'allocating', 'draining', 'not_running', 'unknown']
    .map((state) => ({ state, count: over[state] ?? 0 }))

  it('has nothing to explain when nothing is waiting', () => {
    expect(scaleExplanation({ queueDepth: 0 })).toBe(null)
    expect(scaleExplanation({ queueDepth: null })).toBe(null)
  })

  it('names the configured ceiling when the app is at it', () => {
    const why = scaleExplanation({ queueDepth: 10, capacity: { scale: scale() },
      saturation: { replicas: { running: 4, max: 4, atMax: true } } })
    expect(why.kind).toBe('at_max')
    expect(why.text).toContain('Running 4 replicas, the configured maximum')
  })

  it('blames a revision that cannot come up before it blames the scale rule', () => {
    const why = scaleExplanation({ queueDepth: 10, capacity: { scale: scale() },
      saturation: { replicas: { atMax: true } },
      lifecycle: { blocked: { state: 'Failed', error: 'ImagePullFailure' } } })
    expect(why.kind).toBe('revision')
    expect(why.detail).toBe('ImagePullFailure')
  })

  it('says capacity is arriving when replicas are still coming up', () => {
    const why = scaleExplanation({ queueDepth: 10, capacity: { scale: scale() },
      saturation: { replicas: { running: 2, max: 4, atMax: false } },
      lifecycle: { counts: counts({ ready: 2, starting: 1, allocating: 1 }) } })
    expect(why.kind).toBe('starting')
    expect(why.text).toContain('2 replica(s) are still coming up')
  })

  it('says so when the app has no scale rule at all', () => {
    // A real configuration, and a different answer from "the rules could not be read".
    const why = scaleExplanation({ queueDepth: 10, capacity: { scale: scale({ rules: [] }) },
      saturation: { replicas: { running: 1, max: 4, atMax: false } }, lifecycle: { counts: counts() } })
    expect(why.kind).toBe('no_rule')
    expect(why.text).toContain('no scale rule')
  })

  it('names the rules that could be responsible without claiming one fired', () => {
    // Azure publishes the rules and the replica count, never a decision log.
    const why = scaleExplanation({ queueDepth: 10, capacity: { scale: scale() },
      saturation: { replicas: { running: 1, max: 4, atMax: false } }, lifecycle: { counts: counts() } })
    expect(why.kind).toBe('not_yet')
    expect(why.text).toContain('queue-depth')
    expect(why.text).toContain('polled every 30s')
    expect(why.detail).toMatch(/does not report which scale rule caused/)
  })

  it('admits it cannot say why when the scale rule could not be read', () => {
    const why = scaleExplanation({ queueDepth: 10, capacity: {},
      saturation: { replicas: { atMax: false } }, lifecycle: { counts: counts() } })
    expect(why.kind).toBe('unreported')
    expect(why.text).toMatch(/could not be read, so why is not reported/)
  })
})

describe('Scale events are observations of Azure own replica series', () => {
  const withSeries = (values) => ({ metrics: { replicas: { available: true,
    series: values.map(([offsetS, value]) => ({ at: iso(offsetS), value })) } } })

  it('reads a change between two samples as the event', () => {
    // Azure reports the count over time, never a scale event, so the change IS the event.
    const events = scaleEvents(withSeries([[-180, 1], [-120, 1], [-60, 3], [0, 2]]))
    expect(events.map((e) => [e.from, e.to, e.direction]))
      .toEqual([[1, 3, 'out'], [3, 2, 'in']])
  })

  it('reports nothing from a series too short or too flat to contain a change', () => {
    expect(scaleEvents(withSeries([[0, 2]]))).toEqual([])
    expect(scaleEvents(withSeries([[-60, 2], [0, 2]]))).toEqual([])
    expect(scaleEvents(null)).toEqual([])
    expect(scaleEvents({ metrics: {} })).toEqual([])
  })

  it('skips a gap rather than reading it as a scale to zero', () => {
    const events = scaleEvents(withSeries([[-120, 2], [-60, null], [0, 4]]))
    expect(events).toEqual([])
  })
})

describe('Per-worker job health', () => {
  const snapshot = { summary: { worker_instance_attribution: { available: false, reason: 'no writer yet' } },
    runs: [{ scan_id: 's1', stage: 'assess', owner: 'a@example.org', current_file: 'Report.docx',
      current_rule_id: 'WCAG 1.3.1', current_job_type: 'scan_file', current_job_started_at: iso(-45),
      last_error_class: 'source_rate_limit', max_attempts_seen: 2 },
      { scan_id: 's2', stage: 'remediate', current_file: 'Other.docx' }] }

  it('reads runtime from the claim instant and scopes to the stage', () => {
    const health = workerJobHealth(snapshot, 'assess', { nowMs: NOW })
    expect(health.jobs).toHaveLength(1)
    expect(health.jobs[0]).toMatchObject({ file: 'Report.docx', ruleId: 'WCAG 1.3.1', runtimeS: 45 })
    expect(health.jobs[0].jobType).toBe('scan file')
  })

  it('translates the closed error vocabulary into an operator words', () => {
    const health = workerJobHealth(snapshot, 'assess', { nowMs: NOW })
    expect(health.failing[0]).toMatchObject({ kind: 'source_rate_limit', label: 'Source rate limit', attempts: 2 })
    expect(health.retrying).toBe(true)
  })

  it('carries the reason ACP cannot attribute a job to a replica', () => {
    const health = workerJobHealth(snapshot, 'assess', { nowMs: NOW })
    expect(health.perReplica).toBe(false)
    expect(health.attributionReason).toBe('no writer yet')
  })

  it('gives no runtime when no worker has claimed the job', () => {
    const unclaimed = { ...snapshot,
      runs: [{ ...snapshot.runs[0], current_job_started_at: null }] }
    expect(workerJobHealth(unclaimed, 'assess', { nowMs: NOW }).jobs[0].runtimeS).toBe(null)
  })
})


describe('Each worker service reads its own container app', () => {
  const multi = { configured: true, worker_app_name: 'acp-discovery',
    cpu_cores_per_replica: 1, apps: {
      'acp-discovery': { worker_app_name: 'acp-discovery', cpu_cores_per_replica: 1, memory_per_replica: '2Gi' },
      'acp-assess': { worker_app_name: 'acp-assess', cpu_cores_per_replica: 2, memory_per_replica: '4Gi' },
      'acp-remediate': { worker_app_name: 'acp-remediate', cpu_cores_per_replica: 2, memory_per_replica: '4Gi' },
    } }

  it('gives every service its own reading instead of suppressing two of three', () => {
    expect(capacityForService(multi, { role: 'assess' }).memory_per_replica).toBe('4Gi')
    expect(capacityForService(multi, { role: 'discovery' }).memory_per_replica).toBe('2Gi')
    expect(capacityForService(multi, { role: 'remediate' }).worker_app_name).toBe('acp-remediate')
  })

  it('names a block from its key when the block does not name itself', () => {
    const unnamed = { configured: true, apps: { 'acp-assess': { cpu_cores_per_replica: 2 } } }
    expect(capacityForService(unnamed, { role: 'assess' })).toMatchObject({
      worker_app_name: 'acp-assess', cpu_cores_per_replica: 2 })
  })

  it('returns null rather than the wrong block for a service Azure did not read', () => {
    // The whole point: two of three services used to show nothing because the one measured app
    // was not theirs, and showing that app's figures instead would have been worse than none.
    expect(capacityForService(multi, { role: 'release' })).toBe(null)
    expect(capacityForService(null, { role: 'assess' })).toBe(null)
    expect(capacityForService(multi, {})).toBe(null)
  })

  it('falls back to the single-app behaviour when no apps block is published', () => {
    const single = { configured: true, worker_app_name: 'acp-assess', cpu_cores_per_replica: 2 }
    expect(capacityForService(single, { role: 'assess' })).toBe(single)
    expect(capacityForService(single, { role: 'discovery' })).toBe(null)
  })
})


describe('Throughput, and how it compares with five minutes ago', () => {
  const at = (offsetS, documents) => ({ at: iso(offsetS), documents })

  it('measures the current rate from the counter change over real elapsed time', () => {
    // 60 documents over 300s = 12/min.
    const model = throughputModel([at(-300, 100), at(0, 160)], 'documents', { nowMs: NOW })
    expect(model.current).toBe(12)
  })

  it('compares like with like, both halves measured the same way', () => {
    // Previous five minutes: 30 over 300s = 6/min. Current: 60 over 300s = 12/min.
    const model = throughputModel(
      [at(-600, 70), at(-300, 100), at(-299, 100), at(0, 160)], 'documents', { nowMs: NOW })
    expect(model.previous).toBe(6)
    expect(model.current).toBe(12)
    expect(model.change).toBe(6)
    expect(model.direction).toBe('up')
    expect(model.reason).toBe(null)
  })

  it('refuses a comparison against half a window, and says which half is missing', () => {
    // A tab open four minutes has a rate but nothing honest to compare it against.
    const model = throughputModel([at(-240, 100), at(0, 160)], 'documents', { nowMs: NOW })
    expect(model.current).not.toBe(null)
    expect(model.previous).toBe(null)
    expect(model.change).toBe(null)
    expect(model.reason).toMatch(/needs a full 5 minutes before this one/)
  })

  it('says when there is not even a rate yet', () => {
    expect(throughputModel([at(0, 100)], 'documents', { nowMs: NOW }).reason)
      .toMatch(/two readings at least 30s apart/)
    // Two readings four seconds apart are not a rate either.
    expect(throughputModel([at(-4, 100), at(0, 101)], 'documents', { nowMs: NOW }).current).toBe(null)
  })

  it('treats a counter going backwards as a change of subject, not negative throughput', () => {
    // A redeploy, or a run ageing out of the snapshot's fifteen-minute tail. Work is not un-done.
    expect(throughputModel([at(-300, 160), at(0, 100)], 'documents', { nowMs: NOW }).current).toBe(null)
  })

  it('reports a rate of nothing as nothing, which is a measurement', () => {
    const model = throughputModel([at(-300, 100), at(0, 100)], 'documents', { nowMs: NOW })
    expect(model.current).toBe(0)
    expect(model.reason).toMatch(/needs a full 5 minutes/)
  })

  it('never counts findings that were not counted', () => {
    // Only assess runs carry a findings count; a 0 would read as "no findings found".
    const snapshot = { generated_at: iso(0), summary: { completed_jobs: 40,
      by_stage: { assess: { findings: null }, remediate: { completed: 5 } } } }
    const sample = sampleForNode({ kind: 'queue' }, { snapshot })
    expect(sample.findings).toBe(null)
    expect(sample.documents).toBe(40)
    expect(sample.fixes).toBe(5)
  })
})


describe('Queue health beyond the oldest job', () => {
  const summary = (over = {}) => ({ queued: 10, running: 2, queue: {
    running: 2, waiting: 8, retrying: 0, failed: 0, arrived: 30, completed: 45, window_s: 900,
    oldest_queued_at: iso(-1000), median_queued_at: iso(-500), p95_queued_at: iso(-950),
    wait_sampled: 10, fairness: { tenants: 3, counts: [8, 5, 2], top_share_pct: 53 }, ...over } })

  it('reports the median and the tail, not just the worst job', () => {
    const model = queueModel(summary(), { nowMs: NOW })
    expect(model.oldestWaitS).toBe(1000)
    expect(model.medianWaitS).toBe(500)
    expect(model.p95WaitS).toBe(950)
    expect(model.waitSampled).toBe(10)
  })

  it('leaves a percentile unreported when nothing was sampled', () => {
    const model = queueModel(summary({ median_queued_at: null, p95_queued_at: null, wait_sampled: 0 }),
      { nowMs: NOW })
    expect(model.medianWaitS).toBe(null)
    expect(model.p95WaitS).toBe(null)
  })

  it('models the spread as shares, and never as a list of customers', () => {
    const fairness = fairnessModel({ tenants: 3, counts: [8, 5, 2], top_share_pct: 53 })
    expect(fairness.available).toBe(true)
    expect(fairness.shares).toEqual([53.3, 33.3, 13.3])
    expect(fairness.concentrated).toBe(false)
    expect(JSON.stringify(fairness)).not.toMatch(/@/)
  })

  it('flags a concentrated queue on the same threshold the map banner uses', () => {
    expect(fairnessModel({ tenants: 2, counts: [9, 1], top_share_pct: 90 }).concentrated).toBe(true)
    // One tenant holding all of a queue only it is using is not a fairness problem.
    expect(fairnessModel({ tenants: 1, counts: [12], top_share_pct: 100 }).concentrated).toBe(false)
    expect(fairnessModel({ tenants: 1, counts: [12], top_share_pct: 100 }).topSharePct).toBe(100)
  })

  it('is unavailable rather than empty when the backend reports no fairness block', () => {
    expect(fairnessModel(undefined)).toMatchObject({ available: false, counts: [], concentrated: false })
    expect(fairnessModel({ tenants: 0, counts: [], top_share_pct: null }).available).toBe(false)
  })
})


describe('Request health, and the percentile it refuses to fake', () => {
  const cap = (over = {}) => ({ configured: true, worker_app_name: 'acp-assess',
    metrics_window_minutes: 15,
    metrics: {
      requests: { available: true, latest: 40, series: [
        { at: iso(-120), value: 100 }, { at: iso(-60), value: 110 }, { at: iso(0), value: 90 }] },
      response_ms: { available: true, latest: 42 },
      retries: { available: true, latest: 3 },
      connect_timeouts: { available: false, latest: null },
      ejected_hosts: { available: true, latest: 0 },
    },
    status_classes: { '2xx': 280, '4xx': 18, '5xx': 2 }, ...over })

  it('derives a request rate from the window it was told about', () => {
    // 300 requests over 15 minutes = 20/min.
    expect(requestHealth(cap(), { windowMinutes: 15 }).requestsPerMin).toBe(20)
  })

  it('labels the average as an average and refuses to present it as a percentile', () => {
    // The one quietly wrong thing this panel could do: a p99 blowout barely moves a mean, so the
    // two differ most exactly when latency matters.
    const health = requestHealth(cap())
    expect(health.averageResponseMs).toBe(42)
    expect(health.percentilesAvailable).toBe(false)
    expect(health.percentilesNote).toBe(LATENCY_PERCENTILES_NOTE)
    expect(LATENCY_PERCENTILES_NOTE).toMatch(/not shown rather than approximated from the mean/)
    // The note NAMES the percentiles, as the thing that is missing. What must not exist is a
    // percentile VALUE — a number the reader could act on that was never measured.
    const percentileValues = health.classes.concat([{ name: 'p95', count: health.averageResponseMs }])
      .filter((row) => /^p\d/.test(row.name) && row.count != null)
    expect(percentileValues).toEqual([{ name: 'p95', count: 42 }])   // only the one this test built
    expect(Object.keys(health)).not.toContain('p95')
    expect(Object.keys(health)).not.toContain('p99')
  })

  it('shares out only the classes Azure reported', () => {
    const health = requestHealth(cap())
    const byName = Object.fromEntries(health.classes.map((row) => [row.name, row]))
    expect(byName['2xx']).toMatchObject({ count: 280, sharePct: 93.3 })
    expect(byName['5xx']).toMatchObject({ count: 2, sharePct: 0.7 })
    // A class Azure did not answer for has no count and no share — not a 0% that reads as
    // "none of these happened".
    expect(byName['3xx']).toEqual({ name: '3xx', count: null, sharePct: null })
  })

  it('reports a resiliency counter of zero as zero and an absent one as absent', () => {
    const health = requestHealth(cap())
    expect(health.ejectedHosts).toBe(0)        // a measurement
    expect(health.connectTimeouts).toBe(null)  // not measured
  })

  it('degrades to nothing measured rather than zeroes for a worker app', () => {
    // ACP's workers claim from a queue rather than serving requests, so they have no ingress.
    const health = requestHealth({ configured: true, metrics: {}, status_classes: {} })
    expect(health.requestsPerMin).toBe(null)
    expect(health.averageResponseMs).toBe(null)
    expect(health.classified).toBe(null)
    expect(health.classes.every((row) => row.count === null)).toBe(true)
  })
})


describe('Tracing tells you whether a drill-down exists', () => {
  it('offers the full pivot set only when correlation is actually available', () => {
    const full = tracingModel({ summary: { tracing: { enabled: true, correlation: 'full', sampling_ratio: 1 } } })
    expect(full.enabled).toBe(true)
    expect(full.correlate).toEqual(['run', 'batch', 'job', 'tenant', 'document'])
    expect(full.note).toBe(null)
  })

  it('separates tracing off from tracing on without a salt', () => {
    // Both look like "no per-customer drill-down", and they are different problems: one collects
    // nothing, the other collects spans that join by run but carry no tenant or document id.
    const idsOnly = tracingModel({ summary: { tracing: { enabled: true, correlation: 'ids_only' } } })
    expect(idsOnly.enabled).toBe(true)
    expect(idsOnly.correlate).toEqual(['run', 'batch', 'job'])
    expect(idsOnly.note).toMatch(/ACP_TELEMETRY_SALT is unset/)

    const off = tracingModel({ summary: { tracing: { enabled: false, reason: 'not configured' } } })
    expect(off.correlate).toEqual([])
    expect(off.note).toMatch(/Tracing is off — not configured/)
  })

  it('never offers a link to traces that do not exist', () => {
    // A drill-down into an empty query during an incident is worse than no drill-down.
    expect(tracingModel({ summary: { tracing: { enabled: false, reason: 'exporter failed to start: ValueError' } } }))
      .toMatchObject({ available: false, correlate: [] })
    expect(tracingModel({}).note).toMatch(/does not report whether tracing is configured/)
  })
})

/* ─────────────────────── Active alerts (Tier 5) ─────────────────────── */

import { alertsModel, alertRuleTone, alertRuleState, ALERT_STATES } from './liveOpsDrawer.js'

const rule = (over = {}) => ({
  name: 'cpu-high', severity: 2, severity_label: 'Warning', enabled: true,
  state: 'resolved', since: null, condition: 'Average CpuPercentage GreaterThan 85',
  description: null, window: 'PT5M', frequency: 'PT1M', ...over,
})

describe('alertsModel', () => {
  it('separates "nobody is watching" from "nothing is firing"', () => {
    // The single reason this model exists. Both have an empty firing list; a conventional alerts
    // panel renders both as a green tick, and one of them is a service no alert covers.
    const unmonitored = alertsModel({ alerts: { queried: true, rules_total: 0, rules_enabled: 0, firing: [], rules: [] } })
    const clear = alertsModel({ alerts: { queried: true, rules_total: 1, rules_enabled: 1, firing: [], rules: [rule()] } })

    expect(unmonitored.firing).toEqual(clear.firing)
    expect(unmonitored.state).toBe('unmonitored')
    expect(clear.state).toBe('clear')
    expect(unmonitored.tone).not.toBe('ok')
    expect(clear.tone).toBe('ok')
  })

  it('never claims all-clear when the query itself failed', () => {
    for (const reason of ['permission', 'error']) {
      const m = alertsModel({ alerts: { queried: false, rules_total: null, firing: [], rules: [], unavailable_reason: reason } })
      expect(m.state).toBe('unavailable')
      expect(m.tone).not.toBe('ok')
      expect(m.text).toBe('Not reported')
    }
  })

  it('names the permission case, because it is the one an operator can fix', () => {
    const m = alertsModel({ alerts: { queried: false, firing: [], rules: [], unavailable_reason: 'permission' } })
    expect(m.reason).toMatch(/Monitoring Reader/)
  })

  it('is unavailable, not clear, when there is no alerts block at all', () => {
    expect(alertsModel(null).state).toBe('unavailable')
    expect(alertsModel({}).state).toBe('unavailable')
    expect(alertsModel({ alerts: {} }).state).toBe('unavailable')
  })

  it('reports firing with a count against the rules that exist', () => {
    const fired = rule({ state: 'fired', severity: 0, severity_label: 'Critical' })
    const m = alertsModel({ alerts: { queried: true, rules_total: 3, rules_enabled: 3, firing: [fired], rules: [fired, rule(), rule()] } })
    expect(m.state).toBe('firing')
    expect(m.tone).toBe('bad')
    expect(m.reason).toBe('1 of 3 rules firing.')
  })

  it('counts rules whose state could not be read, rather than folding them into "quiet"', () => {
    // "three rules, one unreadable" is a different situation from "three rules, all quiet", and
    // the difference is exactly the alert that might be firing unseen.
    const m = alertsModel({ alerts: { queried: true, rules_total: 3, rules_enabled: 3, firing: [],
      rules: [rule(), rule(), rule({ state: 'unknown' })] } })
    expect(m.unknownCount).toBe(1)
    expect(m.reason).toMatch(/1 could not be read/)
  })

  it('goes to unknown, not clear, when no rule reported a state at all', () => {
    const m = alertsModel({ alerts: { queried: true, rules_total: 2, rules_enabled: 2, firing: [],
      rules: [rule({ state: 'unknown' }), rule({ state: 'unknown' })] } })
    expect(m.state).toBe('unknown')
    expect(m.tone).not.toBe('ok')
  })

  it('does not count a disabled rule as unreadable — it is not evaluating', () => {
    const m = alertsModel({ alerts: { queried: true, rules_total: 2, rules_enabled: 1, firing: [],
      rules: [rule(), rule({ enabled: false, state: 'unknown' })] } })
    expect(m.unknownCount).toBe(0)
    expect(m.state).toBe('clear')
  })

  it('uses singular wording for one rule', () => {
    const m = alertsModel({ alerts: { queried: true, rules_total: 1, rules_enabled: 1, firing: [], rules: [rule()] } })
    expect(m.reason).toBe('1 rule watching, none firing.')
  })

  it('every state carries a non-colour indicator', () => {
    // WCAG 1.4.1: the icon and the word both have to distinguish these, not the tone alone.
    const icons = Object.values(ALERT_STATES).map(s => s.icon)
    const texts = Object.values(ALERT_STATES).map(s => s.text)
    expect(new Set(icons).size).toBe(icons.length)
    expect(new Set(texts).size).toBe(texts.length)
  })
})

describe('alertRuleTone / alertRuleState', () => {
  it('a rule nobody could read is a warning, never a pass', () => {
    expect(alertRuleTone(rule({ state: 'unknown' }))).toBe('warn')
    expect(alertRuleState(rule({ state: 'unknown' }))).toBe('Not reported')
  })

  it('a disabled rule is idle and says so, rather than reading as clear', () => {
    expect(alertRuleTone(rule({ enabled: false, state: 'fired' }))).toBe('idle')
    expect(alertRuleState(rule({ enabled: false, state: 'fired' }))).toBe('Disabled')
  })

  it('a firing rule takes its severity tone, and severity 0 is the worst', () => {
    expect(alertRuleTone(rule({ state: 'fired', severity: 0 }))).toBe('bad')
    expect(alertRuleTone(rule({ state: 'fired', severity: 3 }))).toBe('info')
  })

  it('a firing rule with an unlabelled severity is still treated as bad, not as info', () => {
    expect(alertRuleTone(rule({ state: 'fired', severity: null }))).toBe('bad')
  })

  it('shows a state Azure invented later as itself rather than guessing', () => {
    expect(alertRuleState(rule({ state: 'suppressed' }))).toBe('Suppressed')
    expect(alertRuleTone(rule({ state: 'suppressed' }))).toBe('warn')
  })
})

/* ─────────────────────── Platform health (Tier 5) ─────────────────────── */

import { resourceHealthModel, serviceHealthModel, incidentRegions, HEALTH_STATES } from './liveOpsDrawer.js'

const transition = (over = {}) => ({
  at: '2026-09-05T11:00:00Z', status: 'Available', previous: 'Unavailable',
  cause: 'PlatformInitiated', summary: null, ...over,
})
const rh = (over = {}) => ({ resource_health: {
  queried: true, status: 'Available', tone: 'ok', previous: 'Unavailable',
  cause: 'PlatformInitiated', reported_at: '2026-09-05T11:00:00Z', summary: null,
  transitions: [transition()], window_hours: 24, unavailable_reason: null, ...over } })

describe('resourceHealthModel', () => {
  it('reports a quiet window as "no health events", never as Available', () => {
    // The single reason this model exists. A quiet 24 hours is the healthy case AND exactly what
    // an outage looks like before Azure ingests it. Claiming Available is the one answer the
    // activity log cannot support.
    const m = resourceHealthModel(rh({ transitions: [], status: null }))
    expect(m.state).toBe('quiet')
    expect(m.text).not.toBe('Available')
    expect(m.tone).not.toBe('ok')
  })

  it('tells the reader to look at the live metrics for right now', () => {
    // Because the quiet state genuinely cannot answer "is it up", it has to say where that answer
    // actually lives rather than leaving a reassuring blank.
    const m = resourceHealthModel(rh({ transitions: [], status: null }))
    expect(m.reason).toMatch(/live metrics/)
    expect(m.reason).toMatch(/24 hours/)
  })

  it('always carries the time the reading was reported, so it cannot read as live', () => {
    const m = resourceHealthModel(rh())
    expect(m.reportedAt).toBe('2026-09-05T11:00:00Z')
    expect(m.reason).toMatch(/Last reported/)
    expect(m.reason).not.toMatch(/\bis (available|healthy)\b/i)
  })

  it('names a platform-initiated cause differently from one we caused', () => {
    expect(resourceHealthModel(rh({ cause: 'PlatformInitiated' })).reason).toMatch(/platform-initiated/)
    expect(resourceHealthModel(rh({ cause: 'UserInitiated' })).reason).toMatch(/a change we made/)
  })

  it('keeps Unknown out of both the healthy and the broken bucket', () => {
    const m = resourceHealthModel(rh({ status: 'Unknown', transitions: [transition({ status: 'Unknown' })] }))
    expect(m.state).toBe('unknown')
    expect(m.tone).toBe('warn')
    expect(HEALTH_STATES.available.tone).toBe('ok')
    expect(HEALTH_STATES.unavailable.tone).toBe('bad')
  })

  it('falls back to unknown for a status Azure invents later, not to available', () => {
    const m = resourceHealthModel(rh({ status: 'Deprovisioning', transitions: [transition({ status: 'Deprovisioning' })] }))
    expect(m.state).toBe('unknown')
    expect(m.tone).not.toBe('ok')
  })

  it('never claims health when the query failed or was not made', () => {
    for (const capacity of [null, {}, { resource_health: {} },
      { resource_health: { queried: false, unavailable_reason: 'permission' } }]) {
      const m = resourceHealthModel(capacity)
      expect(m.state).toBe('unavailable_reading')
      expect(m.tone).not.toBe('ok')
    }
    expect(resourceHealthModel({ resource_health: { queried: false, unavailable_reason: 'permission' } }).reason)
      .toMatch(/Monitoring Reader/)
  })

  it('every state is distinguishable without colour', () => {
    const icons = Object.values(HEALTH_STATES).map(s => s.icon)
    const texts = Object.values(HEALTH_STATES).map(s => s.text)
    expect(new Set(icons).size).toBe(icons.length)
    expect(new Set(texts).size).toBe(texts.length)
  })
})

describe('serviceHealthModel', () => {
  const incident = (over = {}) => ({ tracking_id: 'ABC', kind: 'Incident', stage: 'Active',
    resolved: false, title: 'Networking degradation', summary: 'We are investigating.',
    at: '2026-09-05T11:00:00Z', services: [{ service: 'Container Apps', regions: ['East US'] }], ...over })

  it('splits active from resolved rather than dropping the resolved ones', () => {
    // An incident that cleared twenty minutes ago is the explanation for the restarts still on
    // the timeline; dropping it leaves an operator hunting a cause Azure already published.
    const m = serviceHealthModel({ service_health: { queried: true, window_hours: 24,
      active: [incident(), incident({ tracking_id: 'XYZ', stage: 'Resolved', resolved: true })] } })
    expect(m.active).toHaveLength(1)
    expect(m.resolved).toHaveLength(1)
  })

  it('says nothing happened only when it actually asked', () => {
    const asked = serviceHealthModel({ service_health: { queried: true, window_hours: 24, active: [] } })
    expect(asked.available).toBe(true)
    expect(asked.reason).toMatch(/No Azure incidents/)

    const failed = serviceHealthModel({ service_health: { queried: false, unavailable_reason: 'error', active: [] } })
    expect(failed.available).toBe(false)
    expect(failed.reason).not.toMatch(/No Azure incidents/)
  })

  it('is unavailable, not quiet, with no block at all', () => {
    expect(serviceHealthModel(null).available).toBe(false)
    expect(serviceHealthModel({}).available).toBe(false)
  })
})

describe('incidentRegions', () => {
  it('flattens and de-duplicates the regions Azure named', () => {
    expect(incidentRegions({ services: [
      { service: 'A', regions: ['East US', 'West US'] },
      { service: 'B', regions: ['East US'] }] })).toEqual(['East US', 'West US'])
  })

  it('returns nothing when Azure named no region, rather than guessing one', () => {
    // Guessing from the subscription's own region would attribute an incident to a place it may
    // never have touched.
    expect(incidentRegions({ services: [{ service: 'A' }] })).toEqual([])
    expect(incidentRegions({})).toEqual([])
    expect(incidentRegions({ services: 'not a list' })).toEqual([])
  })
})

/* ─────────────────────── Deployment transparency (Tier 4) ─────────────────────── */

import { deploymentModel, revisionComparisonModel } from './liveOpsDrawer.js'

const gaps = [
  { step: 'Build started', reason: 'Runs in the CI workflow, not in Azure.' },
  { step: 'Image published', reason: 'Happens in the container registry.' },
  { step: 'Smoke test passed', reason: 'Runs in the CI workflow after the rollout.' },
]
const deployBlock = (over = {}) => ({ deployments: {
  queried: true, events: [], window_hours: 24, not_reported: gaps,
  system_logs: { available: false, reason: 'Needs a Log Analytics workspace; lags ~three minutes.' },
  unavailable_reason: null, ...over } })

describe('deploymentModel', () => {
  it('carries the steps Azure cannot see even when the timeline is empty', () => {
    // A timeline that silently begins at "revision created" claims the deployment began there.
    const m = deploymentModel(deployBlock())
    expect(m.notReported.map(g => g.step)).toEqual(
      ['Build started', 'Image published', 'Smoke test passed'])
    expect(m.notReported.every(g => g.reason)).toBe(true)
  })

  it('keeps the system-log gap and its reason', () => {
    const m = deploymentModel(deployBlock())
    expect(m.systemLogs.available).toBe(false)
    expect(m.systemLogs.reason).toMatch(/Log Analytics/)
  })

  it('marks a timeline partial when the activity log failed but revisions did not', () => {
    // Revision milestones come from a call that already succeeded. Presenting the remainder as a
    // whole timeline would hide that Azure's own operations are missing from it.
    const m = deploymentModel(deployBlock({ queried: false, unavailable_reason: 'error',
      events: [{ at: '2026-09-05T09:00:00Z', kind: 'revision', label: 'Revision v2 created',
        status: 'Provisioned', failed: false, detail: null }] }))
    expect(m.available).toBe(true)
    expect(m.partial).toBe(true)
    expect(m.reason).toMatch(/activity-log query failed/)
  })

  it('is not partial when the query succeeded', () => {
    expect(deploymentModel(deployBlock({ events: [{ at: 'x', kind: 'revision', failed: false }] })).partial)
      .toBe(false)
  })

  it('counts failed rows so a bad deploy is not just another line', () => {
    const m = deploymentModel(deployBlock({ events: [
      { at: 'c', kind: 'operation', label: 'Container app updated', failed: true },
      { at: 'b', kind: 'revision', label: 'Revision v2 created', failed: true },
      { at: 'a', kind: 'operation', label: 'Container app updated', failed: false }] }))
    expect(m.failedCount).toBe(2)
  })

  it('says nothing happened only when it actually asked', () => {
    expect(deploymentModel(deployBlock()).reason).toMatch(/No deployment activity/)
    expect(deploymentModel(deployBlock({ queried: false, unavailable_reason: 'permission' })).reason)
      .toMatch(/Monitoring Reader/)
  })

  it('is unavailable with no block at all', () => {
    expect(deploymentModel(null).available).toBe(false)
    expect(deploymentModel({}).available).toBe(false)
  })
})

describe('revisionComparisonModel', () => {
  const revision = (name, over = {}) => ({ name, image: 'acr.io/acp:v1', cpu: 1.0, memory: '2Gi',
    provisioning_state: 'Provisioned', replicas: 2, created_at: '2026-09-05T09:00:00Z', ...over })
  const notCompared = [
    { field: 'error_rate', label: 'Error rate', reason: 'Collected per container app, not per revision.' },
    { field: 'cpu_used', label: 'CPU actually used', reason: 'Per app, not per revision.' },
  ]
  const cmp = (over = {}) => ({ revision_comparison: {
    current: revision('v2', { image: 'acr.io/acp:v2' }), previous: revision('v1'),
    changes: [{ field: 'image', label: 'Image', from: 'acr.io/acp:v1', to: 'acr.io/acp:v2' }],
    rollback: { name: 'v1', image: 'acr.io/acp:v1' }, rollback_reason: null,
    not_compared: notCompared, ...over } })

  it('always carries what it did not compare, and why', () => {
    // Not a footnote: it is the reason the rest of the panel can be trusted.
    const m = revisionComparisonModel(cmp())
    expect(m.notCompared.map(r => r.field)).toEqual(['error_rate', 'cpu_used'])
    expect(m.notCompared.every(r => /per revision/i.test(r.reason))).toBe(true)
  })

  it('reports an image change from and to', () => {
    const m = revisionComparisonModel(cmp())
    expect(m.changes[0]).toMatchObject({ from: 'acr.io/acp:v1', to: 'acr.io/acp:v2' })
    expect(m.reason).toBeNull()
  })

  it('says the revisions match rather than showing an empty change list', () => {
    expect(revisionComparisonModel(cmp({ changes: [] })).reason).toMatch(/unchanged/)
  })

  it('says there is nothing to compare when there is only one revision', () => {
    const m = revisionComparisonModel(cmp({ previous: null, changes: [] }))
    expect(m.reason).toMatch(/nothing to compare/)
  })

  it('passes the rollback reason through when there is no target', () => {
    const m = revisionComparisonModel(cmp({ rollback: null,
      rollback_reason: 'No earlier revision is still provisioned.' }))
    expect(m.rollback).toBeNull()
    expect(m.rollbackReason).toMatch(/still provisioned/)
  })

  it('is unavailable when no active revision was read', () => {
    expect(revisionComparisonModel({ revision_comparison: { current: null } }).available).toBe(false)
    expect(revisionComparisonModel(null).available).toBe(false)
  })
})

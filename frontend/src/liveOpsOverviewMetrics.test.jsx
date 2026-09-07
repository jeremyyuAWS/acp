import { afterEach, describe, expect, it } from 'vitest'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { LiveOpsOverviewMetrics, liveOpsOverviewModel } from './LiveOpsOverviewMetrics.jsx'

const NOW = Date.parse('2026-09-07T12:00:00Z')
const at = (minutes) => new Date(NOW + minutes * 60000).toISOString()
const metric = (latest, values) => ({ available: true, latest,
  series: values.map(([minutes, value]) => ({ at: at(minutes), value })) })
const replicas = Array.from({ length: 7 }, (_, index) => ({ name: `replica-${index + 1}`,
  state: index < 4 ? 'ready' : index < 6 ? 'starting' : 'draining', age_s: 120 + index,
  containers_ready: index < 4 ? 1 : 0, containers: 1, restarts: index }))
const capacity = { configured: true, worker_app_name: 'acp-assess', cpu_cores_per_replica: 2,
  memory_per_replica: '4Gi', replicas,
  replica_lifecycle: { total: 7, counts: { ready: 4, starting: 2, draining: 1 } },
  metrics: {
    replicas: metric(7, [[-15, 5], [0, 7]]),
    cpu_percent: metric(60, [[-15, 45], [0, 60]]),
    memory_percent: metric(70, [[-15, 70], [0, 70]]),
    restarts: metric(4, [[-15, 1], [0, 4]]),
    network_in_bytes: metric(1048576, [[-15, 524288], [0, 1048576]]),
    network_out_bytes: metric(2097152, [[-15, 1048576], [0, 2097152]]),
    reserved_cores: metric(12, [[0, 12]]),
  } }
const service = { role: 'assess' }

afterEach(unmountAll)

async function mount() {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(LiveOpsOverviewMetrics, { capacity, service, nowMs: NOW })) })
  return container
}

describe('LiveOpsOverviewMetrics integration model', () => {
  it('provides six compact metrics with meaningful static deltas over 15 minutes', () => {
    const model = liveOpsOverviewModel({ capacity, service, nowMs: NOW })
    expect(model.metrics.map(({ label }) => label)).toEqual([
      'Replicas', 'CPU', 'Memory', 'Restarts', 'Network in', 'Network out',
    ])
    expect(model.metrics.find(({ key }) => key === 'cpu_percent')).toMatchObject({
      value: '60%', delta: 15, deltaLabel: 'Up 15% over 15 minutes',
    })
    expect(model.metrics.find(({ key }) => key === 'memory_percent')).toMatchObject({
      delta: 0, deltaLabel: 'No change over 15 minutes',
    })
  })

  it('renders static sparklines and does not animate unchanged values', async () => {
    const container = await mount()
    expect(container.querySelectorAll('svg[aria-label*="15-minute trend"]')).toHaveLength(6)
    expect(container.querySelectorAll('animate, animateTransform')).toHaveLength(0)
    expect(container.textContent).toContain('— No change')
  })

  it('summarizes lifecycle and previews only three replicas behind an accessible control', async () => {
    const container = await mount()
    const lifecycle = container.querySelector('[aria-label="Replica lifecycle summary"]')
    expect(lifecycle.textContent).toContain('Ready 4')
    expect(lifecycle.textContent).toContain('Starting 2')
    expect(lifecycle.querySelectorAll('ul[id] > li')).toHaveLength(3)
    const button = lifecycle.querySelector('button[aria-expanded="false"]')
    expect(button.textContent).toBe('Show all 7 replicas')
    await act(async () => { button.click() })
    expect(lifecycle.querySelectorAll('ul[id] > li')).toHaveLength(7)
    expect(lifecycle.querySelector('button').getAttribute('aria-expanded')).toBe('true')
    expect(lifecycle.querySelector('ul[id]').style.maxHeight).toBe('360px')
    expect(lifecycle.querySelector('ul[id]').style.overflowY).toBe('auto')
  })

  it('keeps reserved cores inside collapsed Capacity allocation', async () => {
    const container = await mount()
    const details = container.querySelector('details')
    expect(details.open).toBe(false)
    expect(details.querySelector('summary').textContent).toBe('Capacity allocation')
    expect(details.textContent).toContain('Reserved cores')
    expect(details.textContent).toContain('12 cores')
  })
})

import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: ProcessingStatusPanel } = await import('./ProcessingStatusPanel.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(ProcessingStatusPanel, props)) })
  return container
}
afterEach(() => unmountAll())

describe('ProcessingStatusPanel', () => {
  it('renders nothing for the idle state', async () => {
    const c = await mount({ derived: { state: 'idle', headline: null, detail: null, recommendedAction: null, severity: 'info' } })
    expect(c.textContent).toBe('')
  })

  it('renders nothing when derived is missing entirely', async () => {
    const c = await mount({})
    expect(c.textContent).toBe('')
  })

  it('renders the headline and detail', async () => {
    const c = await mount({
      derived: { state: 'assessing', headline: 'Assessing policy.pdf', detail: '4 of 12 completed', recommendedAction: null, severity: 'active' },
    })
    expect(c.textContent).toContain('Assessing policy.pdf')
    expect(c.textContent).toContain('4 of 12 completed')
  })

  it('shows a Start workers button and calls onStartWorkers when clicked', async () => {
    const onStartWorkers = vi.fn()
    const c = await mount({
      derived: { state: 'no_capacity', headline: 'Waiting for a worker', detail: '', recommendedAction: 'start_workers', severity: 'blocked' },
      onStartWorkers,
    })
    const btn = [...c.querySelectorAll('button')].find((b) => b.textContent === 'Start workers')
    expect(btn).toBeTruthy()
    await act(async () => { btn.click() })
    expect(onStartWorkers).toHaveBeenCalledTimes(1)
  })

  it('does not show a Start workers button when no callback is given', async () => {
    const c = await mount({
      derived: { state: 'no_capacity', headline: 'Waiting for a worker', detail: '', recommendedAction: 'start_workers', severity: 'blocked' },
    })
    expect([...c.querySelectorAll('button')].some((b) => b.textContent === 'Start workers')).toBe(false)
  })

  it('shows the worker-service recommendation for a stalled run', async () => {
    const c = await mount({
      derived: { state: 'stalled', headline: 'Assessment may be stalled', detail: '', recommendedAction: 'check_worker_service', severity: 'warning' },
    })
    expect(c.textContent).toMatch(/check that the worker service is reachable/i)
  })

  it('says pickup time is not available for waiting and no_capacity, but not for assessing or completed', async () => {
    const waiting = await mount({ derived: { state: 'waiting', headline: 'h', detail: '', recommendedAction: null, severity: 'waiting' } })
    expect(waiting.textContent).toMatch(/pickup time not available/i)
    await unmountAll()
    const assessing = await mount({ derived: { state: 'assessing', headline: 'h', detail: '', recommendedAction: null, severity: 'active' } })
    expect(assessing.textContent).not.toMatch(/pickup time not available/i)
  })

  it('renders a "View in Monitor" link that calls onViewMonitor', async () => {
    const onViewMonitor = vi.fn()
    const c = await mount({
      derived: { state: 'waiting', headline: 'h', detail: '', recommendedAction: null, severity: 'waiting' },
      onViewMonitor,
    })
    const link = [...c.querySelectorAll('button')].find((b) => b.textContent.includes('View in Monitor'))
    expect(link).toBeTruthy()
    await act(async () => { link.click() })
    expect(onViewMonitor).toHaveBeenCalledTimes(1)
  })

  it('does not render the Monitor link when no callback is given', async () => {
    const c = await mount({ derived: { state: 'waiting', headline: 'h', detail: '', recommendedAction: null, severity: 'waiting' } })
    expect(c.textContent).not.toMatch(/view in monitor/i)
  })
})

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

  it('shows a Re-run button and calls onRerun when clicked — a different caller, same action shape', async () => {
    const onRerun = vi.fn()
    const c = await mount({
      derived: { state: 'failed', headline: 'Discovery did not finish', detail: '', recommendedAction: 'rerun', severity: 'blocked' },
      onRerun,
    })
    const btn = [...c.querySelectorAll('button')].find((b) => b.textContent === 'Re-run')
    expect(btn).toBeTruthy()
    await act(async () => { btn.click() })
    expect(onRerun).toHaveBeenCalledTimes(1)
  })

  it('shows the worker-service recommendation for a stalled run', async () => {
    const c = await mount({
      derived: { state: 'stalled', headline: 'Assessment may be stalled', detail: '', recommendedAction: 'check_worker_service', severity: 'warning' },
    })
    expect(c.textContent).toMatch(/check that the worker service is reachable/i)
  })

  it('says pickup time is not available when derived sets pickupUnavailable', async () => {
    // Driven by the flag, not a hardcoded state-name list — a caller with its own state
    // vocabulary (Discover, Remediate) sets this explicitly rather than the component guessing
    // from a name it may not recognize. See processingState.js for the Assess states that set it.
    const c = await mount({
      derived: { state: 'waiting', headline: 'h', detail: '', recommendedAction: null, severity: 'waiting', pickupUnavailable: true },
    })
    expect(c.textContent).toMatch(/pickup time not available/i)
  })

  it('does not say pickup time is unavailable when the flag is absent', async () => {
    const c = await mount({
      derived: { state: 'assessing', headline: 'h', detail: '', recommendedAction: null, severity: 'active' },
    })
    expect(c.textContent).not.toMatch(/pickup time not available/i)
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

  it('shows a green "live" badge when derived.live is true', async () => {
    const c = await mount({
      derived: { state: 'discovering', headline: 'Discovering documents', detail: '', recommendedAction: null, severity: 'active', live: true },
    })
    expect(c.textContent).toMatch(/live/)
    expect(c.querySelector('.pulsedot')).toBeTruthy()
  })

  it('does not show the live badge when derived.live is absent — a caller with no such signal', async () => {
    const c = await mount({
      derived: { state: 'discovering', headline: 'Discovering documents', detail: '', recommendedAction: null, severity: 'active' },
    })
    expect(c.querySelector('.pulsedot')).toBeFalsy()
  })

  it('renders a facts grid when given, each as a [label, value] pair', async () => {
    const c = await mount({
      derived: {
        state: 'queued', headline: 'Waiting for a worker', detail: '', recommendedAction: null, severity: 'waiting',
        facts: [{ label: 'Compatible jobs ahead', value: '2' }, { label: 'Worker pool', value: '4 online' }],
      },
    })
    expect(c.textContent).toContain('Compatible jobs ahead')
    expect(c.textContent).toContain('Worker pool')
    expect(c.textContent).toContain('4 online')
  })

  it('renders nothing extra for an empty or missing facts array', async () => {
    const c = await mount({
      derived: { state: 'queued', headline: 'h', detail: '', recommendedAction: null, severity: 'waiting', facts: [] },
    })
    expect(c.textContent).toBe('h')
  })

  it('renders the "Next" hint when given', async () => {
    const c = await mount({
      derived: {
        state: 'queued', headline: 'h', detail: '', recommendedAction: null, severity: 'waiting',
        next: 'A worker will connect to the source and begin discovering documents.',
      },
    })
    expect(c.textContent).toMatch(/Next: A worker will connect/)
  })

  it('does not render a "Next" line when absent', async () => {
    const c = await mount({
      derived: { state: 'queued', headline: 'h', detail: '', recommendedAction: null, severity: 'waiting' },
    })
    expect(c.textContent).not.toMatch(/Next:/)
  })
})

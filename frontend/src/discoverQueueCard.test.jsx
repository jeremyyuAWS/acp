import { describe, it, expect, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// Direct unit coverage for DiscoverQueueCard.jsx — the consolidated "DISCOVERY · Queued" card
// (2026-08-30). The DOM leg in discoverQueueContextAndRate.test.jsx exercises this component only
// through Discover.jsx's real GET /jobs wiring for the common case; this file covers the card's
// own prop-driven branches directly (no-worker state, the provisioning banner, minimal/omitted
// props) that aren't easy to reach that way.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: DiscoverQueueCard } = await import('./DiscoverQueueCard.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(DiscoverQueueCard, props))
  })
  return container
}
afterEach(() => unmountAll())

const rowValue = (c, label) => {
  const labelEl = [...c.querySelectorAll('span')].find((s) => s.textContent === label)
  return labelEl?.nextElementSibling?.textContent ?? null
}

describe('DiscoverQueueCard', () => {
  it('renders nothing but the header and default copy when every optional prop is omitted', async () => {
    const c = await mount({})
    expect(c.textContent).toMatch(/Discovery/)
    expect(c.textContent).toMatch(/Queued/)
    expect(c.textContent).toMatch(/Waiting for a worker/i)
    expect(c.textContent).toMatch(/Your request is safely stored/i)
    // No queue/capacity data given — those sections must not render at all.
    expect(c.textContent).not.toMatch(/Compatible jobs ahead/)
    expect(c.textContent).not.toMatch(/Azure requested/)
  })

  it('shows the no-worker headline and copy when pickupEstimate reports no_worker_available', async () => {
    const c = await mount({ pickupEstimate: { state: 'no_worker_available' } })
    expect(c.textContent).toMatch(/No capacity/)
    expect(c.textContent).toMatch(/No compatible worker is currently ready/i)
    expect(c.textContent).not.toMatch(/Pickup estimate is still being calculated/)
  })

  it('treats a zero-worker, zero-online snapshot as the no-worker state even without pickupEstimate', async () => {
    const c = await mount({ workersTotal: 0, workersOnline: 0 })
    expect(c.textContent).toMatch(/No compatible worker is currently ready/i)
  })

  it('renders an estimated pickup range when pickupEstimate is a resolved estimate', async () => {
    const c = await mount({
      pickupEstimate: {
        state: 'estimated',
        earliest_at: new Date(Date.now() + 2 * 60000).toISOString(),
        latest_at: new Date(Date.now() + 4 * 60000).toISOString(),
      },
    })
    expect(rowValue(c, 'Estimated pickup')).toBe('2–4 min')
  })

  it('falls back to the "still being calculated" copy when there is no resolved estimate and a worker could still claim it', async () => {
    const c = await mount({ pickupEstimate: { state: 'pending' } })
    expect(c.textContent).toMatch(/Pickup estimate is still being calculated\. ACP needs more recent history before it can provide a reliable range\./)
  })

  it('shows the provisioning banner only when Azure reports revision_provisioning_state Provisioning', async () => {
    const c = await mount({
      capacity: { configured: true, revision_provisioning_state: 'Provisioning' },
    })
    expect(c.textContent).toMatch(/Azure is provisioning additional capacity/)
  })

  it('omits the provisioning banner when capacity is not externally managed', async () => {
    const c = await mount({ capacity: { configured: false, revision_provisioning_state: 'Provisioning' } })
    expect(c.textContent).not.toMatch(/provisioning additional capacity/)
  })

  it('renders queue and capacity rows from the given facts, formatting counts and elapsed time', async () => {
    const c = await mount({
      compatibleJobsAhead: 3,
      submittedSecsAgo: 125,
      workersTotal: 4,
      workersOnline: 2,
      replicas: { configured: true, min_replicas: 2 },
      capacity: { configured: true, current_replicas: 1, draining_replicas: 1 },
    })
    expect(rowValue(c, 'Compatible jobs ahead')).toBe('3')
    expect(rowValue(c, 'Submitted')).toBe('2m ago')
    expect(rowValue(c, 'Azure requested')).toBe('2 replicas')
    expect(rowValue(c, 'Azure running')).toBe('1 replica')
    expect(rowValue(c, 'ACP ready')).toBe('4 workers')
    expect(rowValue(c, 'Draining')).toBe('1 replica from an older revision')
  })

  it('shows freshness lines only when the corresponding timestamp is available', async () => {
    const c = await mount({
      queueUpdatedSecsAgo: 3,
      capacity: { configured: true, measured_at: new Date(Date.now() - 18000).toISOString() },
    })
    expect(c.textContent).toMatch(/Queue updated 3s ago/)
    expect(c.textContent).toMatch(/Azure capacity measured 18s ago/)
  })

  it('renders Cancel and View in Monitor only when their handlers are provided, and invokes them on click', async () => {
    let stopped = false
    let viewed = false
    const c = await mount({ onStop: () => { stopped = true }, onViewMonitor: () => { viewed = true } })
    const cancelBtn = [...c.querySelectorAll('button')].find((b) => b.textContent === 'Cancel')
    const monitorBtn = [...c.querySelectorAll('button')].find((b) => b.textContent.includes('View in Monitor'))
    expect(cancelBtn).toBeTruthy()
    expect(monitorBtn).toBeTruthy()
    await act(async () => { cancelBtn.click() })
    await act(async () => { monitorBtn.click() })
    expect(stopped).toBe(true)
    expect(viewed).toBe(true)
  })

  it('omits Cancel and View in Monitor entirely when no handler is given', async () => {
    const c = await mount({})
    expect([...c.querySelectorAll('button')].find((b) => b.textContent === 'Cancel')).toBeFalsy()
    expect([...c.querySelectorAll('button')].find((b) => b.textContent.includes('View in Monitor'))).toBeFalsy()
  })
})

import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const getWorkerRevisions = vi.fn()
vi.mock('./api.js', () => ({
  getWorkerRevisions: (...a) => getWorkerRevisions(...a),
}))

const { default: RevisionHistoryPanel } = await import('./RevisionHistoryPanel.jsx')

let container, root
const mount = async () => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(RevisionHistoryPanel)) })
  return container
}
const settle = async (n = 4) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }

afterEach(() => { unmountAll(); getWorkerRevisions.mockReset() })

const REV_ACTIVE = { name: 'acp-worker--rev-b2c3', active: true, health_state: 'Healthy',
  provisioning_state: 'Provisioned', running_state: 'Running', replicas: 3, traffic_percent: 100,
  created_time: new Date(Date.now() - 3600_000).toISOString() }
const REV_OLD = { name: 'acp-worker--rev-a1b2', active: false, health_state: 'Healthy',
  provisioning_state: 'Provisioned', running_state: 'Running', replicas: 0, traffic_percent: 0,
  created_time: new Date(Date.now() - 86400_000 * 2).toISOString() }

describe('RevisionHistoryPanel', () => {
  it('renders nothing when Azure is not configured', async () => {
    getWorkerRevisions.mockResolvedValue({ configured: false, revisions: [] })
    const c = await mount()
    await settle()
    expect(c.textContent).toBe('')
  })

  it('shows a "no revisions" message when configured but the list is empty', async () => {
    getWorkerRevisions.mockResolvedValue({ configured: true, revisions: [] })
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/No revision history found/)
  })

  it('renders each revision as a table row', async () => {
    getWorkerRevisions.mockResolvedValue({ configured: true, revisions: [REV_ACTIVE, REV_OLD] })
    const c = await mount()
    await settle()
    expect(c.querySelectorAll('tbody tr').length).toBe(2)
  })

  it('shows only the generated suffix of the revision name', async () => {
    getWorkerRevisions.mockResolvedValue({ configured: true, revisions: [REV_ACTIVE] })
    const c = await mount()
    await settle()
    expect(c.textContent).toContain('rev-b2c3')
    expect(c.textContent).not.toContain('acp-worker--rev-b2c3')
  })

  it('marks the active revision', async () => {
    getWorkerRevisions.mockResolvedValue({ configured: true, revisions: [REV_ACTIVE, REV_OLD] })
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/rev-b2c3.*active/s)
  })

  it('shows health and provisioning state together', async () => {
    getWorkerRevisions.mockResolvedValue({ configured: true, revisions: [REV_ACTIVE] })
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/Healthy · Provisioned/)
  })

  it('shows traffic percent and replica count', async () => {
    getWorkerRevisions.mockResolvedValue({ configured: true, revisions: [REV_ACTIVE] })
    const c = await mount()
    await settle()
    expect(c.textContent).toContain('100%')
    expect(c.textContent).toContain('3')
  })

  it('shows an em dash for fields the snapshot does not have', async () => {
    getWorkerRevisions.mockResolvedValue({ configured: true, revisions: [
      { name: 'acp-worker--rev-x', active: false, health_state: null, provisioning_state: null,
        replicas: null, traffic_percent: null, created_time: null } ] })
    const c = await mount()
    await settle()
    expect(c.textContent).toContain('—')
  })

  it('shows an error message when the fetch fails', async () => {
    getWorkerRevisions.mockRejectedValue(new Error('network'))
    const c = await mount()
    await settle()
    expect(c.querySelector('[role="alert"]')?.textContent).toMatch(/Could not load revision history/)
  })

  it('re-fetches when the refresh button is clicked', async () => {
    getWorkerRevisions.mockResolvedValue({ configured: true, revisions: [REV_ACTIVE] })
    const c = await mount()
    await settle()
    expect(getWorkerRevisions).toHaveBeenCalledTimes(1)
    const btn = [...c.querySelectorAll('button')].find((b) => /Refresh/.test(b.textContent))
    await act(async () => { btn.click() })
    await settle()
    expect(getWorkerRevisions).toHaveBeenCalledTimes(2)
  })
})

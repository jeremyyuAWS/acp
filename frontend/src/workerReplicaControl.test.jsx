import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const getWorkerReplicas = vi.fn()
const setWorkerReplicas = vi.fn()

vi.mock('./api.js', () => ({ getWorkerReplicas, setWorkerReplicas }))

const { default: WorkerReplicaControl } = await import('./WorkerReplicaControl.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(WorkerReplicaControl, props)) })
  // Flush the mount effect's promise resolution.
  await act(async () => { await Promise.resolve() })
  return container
}
afterEach(() => unmountAll())
beforeEach(() => { getWorkerReplicas.mockReset(); setWorkerReplicas.mockReset() })

const minus = (c) => c.querySelector('[aria-label="Remove a Container App replica"]')
const plus = (c) => c.querySelector('[aria-label="Add a Container App replica"]')
const click = async (el) => { await act(async () => { el.click() }) }
const admin = { email: 'admin@b.com', is_admin: true }

describe('WorkerReplicaControl', () => {
  it('renders nothing when replica control is not configured on the backend', async () => {
    getWorkerReplicas.mockResolvedValue({ configured: false })
    const c = await mount({ me: admin })
    expect(c.textContent).toBe('')
    expect(minus(c)).toBeFalsy()
  })

  it('renders the current min_replicas and max_replicas when configured', async () => {
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    const c = await mount({ me: admin })
    expect(c.textContent).toMatch(/2/)
    expect(c.textContent).toMatch(/Azure replicas \(max 5\)/)
  })

  it('does not render a leading separator by default', async () => {
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    const c = await mount({ me: admin })
    expect(c.querySelector('.muted')?.textContent).not.toBe('·')
  })

  it('renders a leading separator when asked (AssessRunner\'s inline-row context)', async () => {
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    const c = await mount({ leadingSeparator: true, me: admin })
    const mutedSpans = [...c.querySelectorAll('.muted')].map((s) => s.textContent)
    expect(mutedSpans).toContain('·')
  })

  it('increments optimistically, then reconciles with the server response', async () => {
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    const c = await mount({ me: admin })
    let resolve
    setWorkerReplicas.mockReturnValue(new Promise((r) => { resolve = r }))
    await click(plus(c))
    // Optimistic bump shows immediately, before the server responds.
    expect(c.textContent).toMatch(/3/)
    expect(setWorkerReplicas).toHaveBeenCalledWith(3)
    await act(async () => { resolve({ configured: true, min_replicas: 3, max_replicas: 5 }) })
    expect(c.textContent).toMatch(/3/)
  })

  it('rolls back the optimistic update when the server call fails', async () => {
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    const c = await mount({ me: admin })
    setWorkerReplicas.mockRejectedValue(new Error('nope'))
    await click(plus(c))
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    expect(c.textContent).toMatch(/\b2\b/)
    expect(c.textContent).not.toMatch(/\b3\b/)
  })

  it('will not go below 1 or above max_replicas', async () => {
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 1, max_replicas: 2 })
    const c = await mount({ me: admin })
    expect(minus(c).disabled).toBe(true)
    setWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 2 })
    await click(plus(c))
    await act(async () => { await Promise.resolve() })
    expect(plus(c).disabled).toBe(true)
  })
})

// Found live 2026-08-29: this control rendered its +/- buttons for EVERY caller with no admin
// check, even though PATCH /control/workers/replicas is admin-only (#950) — a non-admin's click
// would 403 server-side and silently revert with no message. GET stays open to everyone, so the
// count itself must still render; only the mutating buttons are gated on me?.is_admin.
describe('WorkerReplicaControl admin gating', () => {
  it('shows the replica count but no adjust buttons for a non-admin caller', async () => {
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    const c = await mount({ me: { email: 'a@b.com', is_admin: false } })
    expect(c.textContent).toMatch(/Azure replicas \(max 5\)/)
    expect(plus(c)).toBeFalsy()
    expect(minus(c)).toBeFalsy()
  })

  it('shows the replica count but no adjust buttons when no me prop is given at all', async () => {
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    const c = await mount()
    expect(c.textContent).toMatch(/Azure replicas \(max 5\)/)
    expect(plus(c)).toBeFalsy()
    expect(minus(c)).toBeFalsy()
  })

  it('never calls setWorkerReplicas for a non-admin, even if a button were somehow clicked', async () => {
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    await mount({ me: { email: 'a@b.com', is_admin: false } })
    expect(setWorkerReplicas).not.toHaveBeenCalled()
  })
})

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

describe('WorkerReplicaControl', () => {
  it('renders nothing when replica control is not configured on the backend', async () => {
    getWorkerReplicas.mockResolvedValue({ configured: false })
    const c = await mount()
    expect(c.textContent).toBe('')
    expect(minus(c)).toBeFalsy()
  })

  it('renders the current min_replicas and max_replicas when configured', async () => {
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    const c = await mount()
    expect(c.textContent).toMatch(/2/)
    expect(c.textContent).toMatch(/Azure replicas \(max 5\)/)
  })

  it('does not render a leading separator by default', async () => {
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    const c = await mount()
    expect(c.querySelector('.muted')?.textContent).not.toBe('·')
  })

  it('renders a leading separator when asked (AssessRunner\'s inline-row context)', async () => {
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    const c = await mount({ leadingSeparator: true })
    const mutedSpans = [...c.querySelectorAll('.muted')].map((s) => s.textContent)
    expect(mutedSpans).toContain('·')
  })

  it('increments optimistically, then reconciles with the server response', async () => {
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 5 })
    const c = await mount()
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
    const c = await mount()
    setWorkerReplicas.mockRejectedValue(new Error('nope'))
    await click(plus(c))
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    expect(c.textContent).toMatch(/\b2\b/)
    expect(c.textContent).not.toMatch(/\b3\b/)
  })

  it('will not go below 1 or above max_replicas', async () => {
    getWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 1, max_replicas: 2 })
    const c = await mount()
    expect(minus(c).disabled).toBe(true)
    setWorkerReplicas.mockResolvedValue({ configured: true, min_replicas: 2, max_replicas: 2 })
    await click(plus(c))
    await act(async () => { await Promise.resolve() })
    expect(plus(c).disabled).toBe(true)
  })
})

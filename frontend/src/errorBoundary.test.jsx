import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

// Suppress the console.error React fires when a boundary catches — it is expected here.
beforeEach(() => { vi.spyOn(console, 'error').mockImplementation(() => {}) })
afterEach(async () => { await unmountAll(); vi.restoreAllMocks() })

const { default: ErrorBoundary } = await import('./ErrorBoundary.jsx')

function Throws() { throw new Error('boom') }
function Fine() { return createElement('span', null, 'all good') }

const mount = async (child) => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(ErrorBoundary, null, child)) })
  return container
}

describe('ErrorBoundary', () => {
  it('renders children transparently when nothing throws', async () => {
    const c = await mount(createElement(Fine))
    expect(c.textContent).toMatch(/all good/)
    expect(c.querySelector('[role="alert"]')).toBeNull()
  })

  it('renders a role=alert fallback when a child throws', async () => {
    const c = await mount(createElement(Throws))
    const alert = c.querySelector('[role="alert"]')
    expect(alert).toBeTruthy()
    expect(alert.textContent).toMatch(/Something went wrong/)
  })

  it('fallback contains a Reload button', async () => {
    const c = await mount(createElement(Throws))
    const btn = c.querySelector('[role="alert"] button')
    expect(btn).toBeTruthy()
    expect(btn.textContent).toBe('Reload')
  })

  it('logs the caught error via componentDidCatch', async () => {
    await mount(createElement(Throws))
    expect(console.error).toHaveBeenCalled()
    const firstErr = console.error.mock.calls.flat().find((a) => a instanceof Error)
    expect(firstErr.message).toBe('boom')
  })
})

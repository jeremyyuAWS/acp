import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import LiveCounter from './LiveCounter.jsx'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(LiveCounter, props)) })
  return container
}
const update = async (props) => {
  await act(async () => { root.render(createElement(LiveCounter, props)) })
  return container
}
afterEach(() => { unmountAll(); vi.restoreAllMocks() })

// Waits for the count-up animation to finish converging without hardcoding COUNT_UP_MS here —
// several short real-time ticks let jsdom's requestAnimationFrame polyfill run its course.
const settle = async (n = 8) => {
  for (let i = 0; i < n; i++) {
    await act(async () => { await new Promise((r) => setTimeout(r, 60)) })
  }
}

describe('LiveCounter', () => {
  it('shows the initial value with no delta badge and no flash', async () => {
    const c = await mount({ value: 1009 })
    expect(c.textContent).toBe('1,009')
    expect(c.querySelector('.livecounter-delta')).toBeFalsy()
    expect(c.querySelector('.livecounter-n.flash')).toBeFalsy()
  })

  it('counts up to a new higher value and shows a "+N" delta', async () => {
    await mount({ value: 1009 })
    await update({ value: 1033 })
    await settle()
    expect(c().textContent).toContain('1,033')
    expect(c().querySelector('.livecounter-delta').textContent).toBe('+24')
    expect(c().querySelector('.livecounter-n.flash')).toBeTruthy()
  })

  it('does not flash or show a delta on a decrease — jumps straight to the lower number', async () => {
    await mount({ value: 1033 })
    await update({ value: 1009 })
    await settle(2)
    expect(c().textContent).toBe('1,009')
    expect(c().querySelector('.livecounter-delta')).toBeFalsy()
    expect(c().querySelector('.livecounter-n.flash')).toBeFalsy()
  })

  it('does not animate or flash between two identical values', async () => {
    await mount({ value: 500 })
    await update({ value: 500 })
    await settle(2)
    expect(c().textContent).toBe('500')
    expect(c().querySelector('.livecounter-delta')).toBeFalsy()
  })

  it('skips the count-up animation under prefers-reduced-motion, but still shows the delta', async () => {
    vi.stubGlobal('matchMedia', (query) => ({
      matches: query.includes('reduce'), media: query,
      addEventListener() {}, removeEventListener() {},
    }))
    await mount({ value: 10 })
    await update({ value: 34 })
    // No settle() needed: reduced motion means the new value is set synchronously in the same
    // effect, not discovered gradually over animation frames.
    expect(c().textContent).toContain('34')
    expect(c().querySelector('.livecounter-delta').textContent).toBe('+24')
  })

  it('the delta badge disappears on its own after its visible window', async () => {
    vi.useFakeTimers()
    await mount({ value: 10 })
    await update({ value: 34 })
    expect(c().querySelector('.livecounter-delta')).toBeTruthy()
    await act(async () => { vi.advanceTimersByTime(2100) })
    expect(c().querySelector('.livecounter-delta')).toBeFalsy()
    vi.useRealTimers()
  })
})

function c() { return container }

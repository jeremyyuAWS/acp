import { act, createElement } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import { useForecastDelta } from './useForecastDelta.js'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
function Probe(props) { const d = useForecastDelta(props.value, props.context, props.setting); return createElement('span', null, d ? `${d.amount}:${d.id}` : '') }
beforeEach(() => vi.useFakeTimers())
afterEach(async () => { await unmountAll(); vi.useRealTimers() })
async function setup() {
  const { root, container } = createTestRoot()
  const render = async (value, setting = 'a', context = 'run1') => act(async () => root.render(createElement(Probe, { value, setting, context })))
  await render(10)
  return { container, render }
}
it('shows a settled setting delta for exactly two seconds across loading gaps', async () => {
  const { container, render } = await setup()
  expect(container.textContent).toBe('')
  await render(null, null)
  await render(15, 'b')
  expect(container.textContent).toBe('5:1')
  await act(async () => vi.advanceTimersByTime(1999))
  expect(container.textContent).toBe('5:1')
  await act(async () => vi.advanceTimersByTime(1))
  expect(container.textContent).toBe('')
})
it('restarts the timer on a rapid setting change and supports decreases', async () => {
  const { container, render } = await setup()
  await render(15, 'b')
  await act(async () => vi.advanceTimersByTime(1500))
  await render(12, 'c')
  expect(container.textContent).toBe('-3:2')
  await act(async () => vi.advanceTimersByTime(500))
  expect(container.textContent).toBe('-3:2')
  await act(async () => vi.advanceTimersByTime(1500))
  expect(container.textContent).toBe('')
})
it('does not animate polling, unchanged totals, or a different assessment', async () => {
  const { container, render } = await setup()
  await render(12)
  expect(container.textContent).toBe('')
  await render(12, 'b')
  expect(container.textContent).toBe('')
  await render(15, 'c')
  await render(100, 'd', 'run2')
  expect(container.textContent).toBe('')
})

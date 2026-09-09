import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import Policy from './RemediationReviewPolicy.jsx'
afterEach(unmountAll)
globalThis.IS_REACT_ACT_ENVIRONMENT = true

it('requires explicit opt-in and emits a bounded review-all preference', async () => {
  const onChange = vi.fn(); const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Policy, { supported: true, onChange })))
  expect(container.querySelector('input').checked).toBe(false)
  await act(async () => container.querySelector('input').click())
  expect(onChange).toHaveBeenCalledWith({ enabled:true, mode:'review_all', minimum_reliability:95, max_review_attempts:1 })
})

it('makes unsupported controls unavailable and explains human approval is retained', async () => {
  const onChange = vi.fn(); const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Policy, { onChange, supported:false })))
  expect(container.querySelector('fieldset').disabled).toBe(true)
  expect(container.textContent).toContain('not available on this server')
  await act(async () => container.querySelector('input').click())
  expect(onChange).not.toHaveBeenCalled()
})

it('bounds review attempts and labels threshold as a saved preference, not automatic approval', async () => {
  const onChange = vi.fn(); const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Policy, { onChange, supported:true, value:{enabled:true} })))
  expect([...container.querySelector('select').options].map(o=>o.value)).toEqual(['1','2'])
  expect(container.textContent).toContain('Every AI suggestion still requires your approval')
  expect(container.textContent).toContain('preference is ready for a future validated-auto policy')
  expect(container.querySelector('input[type=number]').min).toBe('90')
  expect(container.querySelector('input[type=number]').max).toBe('100')
})

it('lets a calibrated execution path choose validated automatic approval and threshold', async () => {
  const onChange = vi.fn(); const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Policy, { onChange, supported:true,
    automaticSupported:true, administratorFloor:97, value:{enabled:true} })))
  const threshold = container.querySelector('input[value="threshold"]')
  await act(async () => threshold.click())
  expect(onChange).toHaveBeenCalledWith({ enabled:true, mode:'threshold', minimum_reliability:95, max_review_attempts:1 })
  expect(container.querySelector('input[type=number]').disabled).toBe(false)
})

it('keeps the validated automatic option unavailable until calibration and independent checks exist', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Policy, { onChange: vi.fn(), supported:true, value:{enabled:true} })))
  expect(container.querySelector('input[value="threshold"]').closest('fieldset').disabled).toBe(true)
  expect(container.textContent).toContain('current calibration data')
  expect(container.textContent).toContain('Suggestions will continue to come to you for approval')
})

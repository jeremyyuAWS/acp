import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationWorkspaceTabs from './RemediationWorkspaceTabs.jsx'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
beforeEach(() => {
  history.replaceState({}, '', '/?tab=remediate')
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  HTMLDialogElement.prototype.close = function () { this.open = false }
})
afterEach(async () => { await unmountAll(); vi.unstubAllGlobals() })
const props = { runId: 'one', plan: createElement('input', { defaultValue: 'draft' }), live: 'live content', review: 'review content' }
async function mount(extra = {}) {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(RemediationWorkspaceTabs, { ...props, ...extra })))
  return { root, container }
}
it('has only Live and Review tabs and defaults to Live', async () => {
  const { container } = await mount()
  expect([...container.querySelectorAll('[role=tab]')].map(n => n.textContent)).toEqual(['Live', 'Review'])
  expect(container.querySelector('#rem-panel-live').hidden).toBe(false)
  expect(container.querySelector('dialog').open).toBe(false)
})
it('opens the plan as a modal, preserves edits on cancel, and retains the mode explanation', async () => {
  const { container } = await mount()
  const trigger = [...container.querySelectorAll('button')].find(n => n.textContent === 'Remediation plan')
  trigger.focus()
  await act(async () => trigger.click())
  const dialog = container.querySelector('dialog')
  expect(dialog.open).toBe(true)
  dialog.querySelector('input').value = 'my choices'
  expect(dialog.textContent).toContain('How modes work')
  await act(async () => dialog.dispatchEvent(new Event('cancel', { bubbles: true, cancelable: true })))
  expect(dialog.open).toBe(false)
  expect(document.activeElement).toBe(trigger)
  await act(async () => trigger.click())
  expect(dialog.querySelector('input').value).toBe('my choices')
})
it.each(['plan', 'modes'])('opens legacy %s URLs in the plan dialog', async mode => {
  history.replaceState({}, '', `/?tab=remediate&mode=${mode}`)
  const { container } = await mount()
  expect(container.querySelector('dialog').open).toBe(true)
  expect(container.querySelectorAll('[role=tab]')).toHaveLength(2)
})
it('closes the plan and reveals Live on an accepted launch', async () => {
  history.replaceState({}, '', '/?tab=remediate&mode=plan')
  const { root, container } = await mount()
  await act(async () => root.render(createElement(RemediationWorkspaceTabs, { ...props, workspaceRequest: { mode: 'live' } })))
  expect(container.querySelector('dialog').open).toBe(false)
  expect(container.querySelector('#rem-panel-live').hidden).toBe(false)
})
it('supports keyboard wraparound and browser history', async () => {
  const { container } = await mount()
  const live = container.querySelector('#rem-mode-live')
  const review = container.querySelector('#rem-mode-review')
  await act(async () => live.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true })))
  expect(document.activeElement).toBe(review)
  expect(container.querySelector('#rem-panel-review').hidden).toBe(false)
  await act(async () => review.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true })))
  expect(document.activeElement).toBe(live)
  history.replaceState({}, '', '/?tab=remediate&mode=plan')
  await act(async () => window.dispatchEvent(new PopStateEvent('popstate')))
  expect(container.querySelector('dialog').open).toBe(true)
})
it('does not display a review badge for another run', async () => {
  const { container } = await mount({ reviewCount: 19, snapshot: { run_id: 'other', batch_id: 'batch' } })
  expect(container.querySelector('#rem-mode-review').textContent).toBe('Review')
})

it('returns to Review after closing the plan without starting', async () => {
  history.replaceState({}, '', '/?tab=remediate&mode=review')
  const { container } = await mount()
  await act(async () => [...container.querySelectorAll('button')].find(n => n.textContent === 'Remediation plan').click())
  await act(async () => container.querySelector('button[aria-label="Close remediation plan"]').click())
  expect(container.querySelector('#rem-panel-review').hidden).toBe(false)
})
it('does not let a delayed header focus move focus after subsequent keyboard navigation', async () => {
  let pending
  vi.stubGlobal('requestAnimationFrame', vi.fn(fn => { pending = fn; return 1 }))
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  const { root, container } = await mount()
  await act(async () => root.render(createElement(RemediationWorkspaceTabs, { ...props, workspaceRequest: { mode: 'review' } })))
  await act(async () => container.querySelector('#rem-mode-review').dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true })))
  await act(async () => pending())
  expect(document.activeElement).toBe(container.querySelector('#rem-mode-live'))
})

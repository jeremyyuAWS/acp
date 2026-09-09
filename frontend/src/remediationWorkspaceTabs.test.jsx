import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(async () => { await unmountAll(); vi.unstubAllGlobals() })
import { prepareWorkflowEntry } from './workflowEntry.js'
import RemediationWorkspaceTabs from './RemediationWorkspaceTabs.jsx'

const snapshot = {
  run_id: 'scan-1', state: 'running', terminal: false, total_documents: 10,
  message: 'Remediation in progress', phases: [],
  documents: { completed: 2, processing: 3, waiting: 4, review: 1, failed: 0, skipped: 0 },
  fixes: { applied: 4, verified: 4 }, delivery: { delivered: 0, pending: 0, awaiting_release: 2 },
  integrity: { ok: true, affected: [] },
}

describe('the three-mode remediation workspace', () => {
  beforeEach(() => {
    sessionStorage.clear()
    history.replaceState({}, '', '/?tab=remediate')
  })

  async function mount(props = {}) {
    const { root, container: host } = createTestRoot()
    await act(async () => root.render(createElement(RemediationWorkspaceTabs, {
      runId: 'scan-1', reviewCount: 2, snapshot, connected: true,
      plan: createElement('input', { 'data-testid': 'plan-state', defaultValue: 'saved selection' }),
      review: createElement('div', { 'data-testid': 'review-state' }, 'review body'),
      live: createElement('div', { 'data-testid': 'live-state' }, 'live body'),
      ...props,
    })))
    return { root, host }
  }

  it('opens Plan on workflow entry even when an earlier visit left mode=live', async () => {
    history.replaceState({}, '', '/?tab=remediate&mode=live')
    const { host } = await mount()
    expect(host.querySelector('#rem-panel-live').hidden).toBe(false)
    await act(async () => prepareWorkflowEntry('remediate'))
    expect(host.querySelector('#rem-panel-plan').hidden).toBe(false)
    expect(new URLSearchParams(location.search).get('mode')).toBe('plan')
    await act(async () => host.querySelector('#rem-mode-live').click())
    expect(host.querySelector('#rem-panel-live').hidden).toBe(false)
  })

  it('defaults to Plan even when decisions exist and keeps all panels mounted', async () => {
    const { host } = await mount()
    const tabs = host.querySelectorAll('[role="tab"]')
    expect(tabs).toHaveLength(3)
    expect(tabs[0].getAttribute('aria-selected')).toBe('true')
    expect(Array.from(tabs, tab => tab.textContent.trim())).toEqual(['Plan', 'Live●', 'Review2'])
    expect(host.querySelector('#rem-panel-plan').hidden).toBe(false)
    expect(host.querySelector('[data-testid="review-state"]')).toBeTruthy()
    expect(host.querySelector('[data-testid="live-state"]')).toBeTruthy()
    expect(host.querySelector('#rem-panel-live').hidden).toBe(true)
    expect(host.querySelector('[data-testid="rem-run-card"]')).toBeNull()
  })

  it('defaults to Plan when automated work is active and review is empty', async () => {
    const { host } = await mount({ reviewCount: 0 })
    expect(host.querySelector('#rem-mode-plan').getAttribute('aria-selected')).toBe('true')
    expect(host.querySelector('[data-testid="live-state"]')).toBeTruthy()
  })

  it('uses the single app-level compact card instead of rendering a duplicate', async () => {
    const { host } = await mount()
    expect(host.querySelector('[data-testid="rem-run-card"]')).toBeNull()
    await act(async () => host.querySelector('#rem-mode-live').click())
    expect(host.querySelector('#rem-panel-live').hidden).toBe(false)
    await act(async () => host.querySelector('#rem-mode-review').click())
    expect(host.querySelector('#rem-panel-review').hidden).toBe(false)
  })

  it('switches with arrow keys without focusing the panel heading', async () => {
    const { host } = await mount()
    const reviewTab = host.querySelector('#rem-mode-review')
    reviewTab.focus()
    await act(async () => reviewTab.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'ArrowLeft', bubbles: true,
    })))
    expect(host.querySelector('#rem-mode-live').getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(host.querySelector('#rem-mode-live'))
    expect(new URLSearchParams(location.search).get('mode')).toBe('live')
  })

  it('defaults to Plan before any work and preserves its input across switches', async () => {
    const { host } = await mount({ reviewCount: 0, snapshot: null })
    expect(host.querySelector('#rem-mode-plan').getAttribute('aria-selected')).toBe('true')
    const input = host.querySelector('[data-testid="plan-state"]')
    input.value = 'changed selection'
    await act(async () => host.querySelector('#rem-mode-live').click())
    await act(async () => host.querySelector('#rem-mode-plan').click())
    expect(host.querySelector('[data-testid="plan-state"]')).toBe(input)
    expect(input.value).toBe('changed selection')
  })

  it.each(['plan', 'review', 'live'])('preserves the %s deep link', async mode => {
    history.replaceState({}, '', `/?tab=remediate&mode=${mode}`)
    const { host } = await mount()
    expect(host.querySelector(`#rem-panel-${mode}`).hidden).toBe(false)
  })

  it('moves to Live after an accepted launch, and allows returning to Plan', async () => {
    history.replaceState({}, '', '/?tab=remediate&mode=plan')
    const { root, host } = await mount()
    await act(async () => root.render(createElement(RemediationWorkspaceTabs, {
      runId: 'scan-1', workspaceRequest: { mode: 'live' }, snapshot,
    })))
    expect(host.querySelector('#rem-panel-live').hidden).toBe(false)
    expect(new URLSearchParams(location.search).get('mode')).toBe('live')
    await act(async () => host.querySelector('#rem-mode-plan').click())
    expect(host.querySelector('#rem-panel-plan').hidden).toBe(false)
  })

  it.each(['plan', 'review'])('reveals %s from a header action', async mode => {
    history.replaceState({}, '', '/?tab=remediate&mode=live')
    const { root, host } = await mount()
    await act(async () => root.render(createElement(RemediationWorkspaceTabs, {
      runId: 'scan-1', workspaceRequest: { mode }, snapshot,
    })))
    expect(host.querySelector(`#rem-panel-${mode}`).hidden).toBe(false)
  })

  it('supports Home, End, wraparound, and browser history', async () => {
    const { host } = await mount()
    async function press(id, key) {
      await act(async () => host.querySelector(id).dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true })))
    }
    await press('#rem-mode-review', 'Home')
    expect(document.activeElement.id).toBe('rem-mode-plan')
    await press('#rem-mode-plan', 'ArrowLeft')
    expect(document.activeElement.id).toBe('rem-mode-review')
    await press('#rem-mode-review', 'ArrowRight')
    expect(document.activeElement.id).toBe('rem-mode-plan')
    await press('#rem-mode-plan', 'End')
    expect(document.activeElement.id).toBe('rem-mode-review')
    history.replaceState({}, '', '/?tab=remediate&mode=plan')
    await act(async () => window.dispatchEvent(new PopStateEvent('popstate')))
    expect(host.querySelector('#rem-panel-plan').hidden).toBe(false)
  })

  function holdAnimationFrames() {
    const callbacks = []
    vi.stubGlobal('requestAnimationFrame', vi.fn(callback => { callbacks.push(callback); return callbacks.length }))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    // Deliberately invoke saved callbacks even after cancellation, to exercise stale work.
    return async () => act(async () => { callbacks.splice(0).forEach(callback => callback(0)) })
  }

  it('does not focus a replacement workspace from an unmounted request', async () => {
    const flushFrames = holdAnimationFrames()
    const first = await mount()
    await act(async () => first.root.render(createElement(RemediationWorkspaceTabs, {
      runId: 'scan-1', workspaceRequest: { mode: 'review' }, snapshot,
    })))
    await unmountAll()
    const { host } = await mount()
    const tab = host.querySelector('#rem-mode-plan')
    await act(async () => tab.click())
    tab.focus()
    await flushFrames()
    expect(document.activeElement).toBe(tab)
    expect(cancelAnimationFrame).toHaveBeenCalled()
  })

  it.each(['keyboard', 'history', 'new run'])('cancels pending panel focus after %s navigation', async navigation => {
    const flushFrames = holdAnimationFrames()
    const { root, host } = await mount()
    const workspaceRequest = { mode: 'review' }
    await act(async () => root.render(createElement(RemediationWorkspaceTabs, { runId: 'scan-1', workspaceRequest, snapshot })))
    const tab = host.querySelector('#rem-mode-plan')
    if (navigation === 'keyboard') {
      await act(async () => host.querySelector('#rem-mode-review').dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true })))
    } else if (navigation === 'history') {
      history.replaceState({}, '', '/?tab=remediate&mode=plan')
      await act(async () => window.dispatchEvent(new PopStateEvent('popstate')))
      tab.focus()
    } else {
      history.replaceState({}, '', '/?tab=remediate&mode=plan')
      await act(async () => root.render(createElement(RemediationWorkspaceTabs, { runId: 'scan-2', workspaceRequest, snapshot })))
      tab.focus()
    }
    await flushFrames()
    expect(document.activeElement).toBe(tab)
    expect(cancelAnimationFrame).toHaveBeenCalled()
  })

  it('focuses only the latest requested panel', async () => {
    const flushFrames = holdAnimationFrames()
    const { root, host } = await mount()
    for (const mode of ['live', 'plan']) await act(async () => root.render(createElement(RemediationWorkspaceTabs, {
      runId: 'scan-1', workspaceRequest: { mode }, snapshot,
    })))
    await flushFrames()
    expect(document.activeElement).toBe(host.querySelector('#rem-panel-plan'))
  })

  it('does not let a previous session choice override the default Plan tab', async () => {
    sessionStorage.setItem('acp-remediation-mode-scan-1', 'live')
    const { host } = await mount()
    expect(host.querySelector('#rem-mode-plan').getAttribute('aria-selected')).toBe('true')
  })
})

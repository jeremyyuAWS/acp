import { beforeEach, describe, expect, it } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import RemediationWorkspaceTabs from './RemediationWorkspaceTabs.jsx'

const snapshot = {
  run_id: 'scan-1', state: 'running', terminal: false, total_documents: 10,
  message: 'Remediation in progress', phases: [],
  documents: { completed: 2, processing: 3, waiting: 4, review: 1, failed: 0, skipped: 0 },
  fixes: { applied: 4, verified: 4 }, delivery: { delivered: 0, pending: 0, awaiting_release: 2 },
  integrity: { ok: true, affected: [] },
}

describe('the two-mode remediation workspace', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="root"></div>'
    sessionStorage.clear()
    history.replaceState({}, '', '/?tab=remediate')
  })

  async function mount(props = {}) {
    const root = createRoot(document.getElementById('root'))
    await act(async () => root.render(createElement(RemediationWorkspaceTabs, {
      runId: 'scan-1', reviewCount: 2, snapshot, connected: true,
      review: createElement('div', { 'data-testid': 'review-state' }, 'review body'),
      live: createElement('div', { 'data-testid': 'live-state' }, 'live body'),
      ...props,
    })))
    return { root, host: document.getElementById('root') }
  }

  it('defaults to review when decisions exist and keeps both panels mounted', async () => {
    const { host } = await mount()
    const tabs = host.querySelectorAll('[role="tab"]')
    expect(tabs).toHaveLength(2)
    expect(tabs[0].getAttribute('aria-selected')).toBe('true')
    expect(host.querySelector('[data-testid="review-state"]')).toBeTruthy()
    expect(host.querySelector('[data-testid="live-state"]')).toBeTruthy()
    expect(host.querySelector('#rem-panel-live').hidden).toBe(true)
  })

  it('defaults to live when automated work is active and review is empty', async () => {
    const { host } = await mount({ reviewCount: 0 })
    expect(host.querySelector('#rem-mode-live').getAttribute('aria-selected')).toBe('true')
  })

  it('switches with arrow keys without focusing the panel heading', async () => {
    const { host } = await mount()
    const reviewTab = host.querySelector('#rem-mode-review')
    reviewTab.focus()
    await act(async () => reviewTab.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'ArrowRight', bubbles: true,
    })))
    expect(host.querySelector('#rem-mode-live').getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(host.querySelector('#rem-mode-live'))
    expect(new URLSearchParams(location.search).get('mode')).toBe('live')
  })

  it('restores an explicit choice for the run', async () => {
    sessionStorage.setItem('acp-remediation-mode-scan-1', 'live')
    const { host } = await mount()
    expect(host.querySelector('#rem-mode-live').getAttribute('aria-selected')).toBe('true')
  })
})

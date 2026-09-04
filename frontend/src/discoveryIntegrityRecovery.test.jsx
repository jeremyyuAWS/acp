import React from 'react'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import DiscoveryIntegrityRecovery from './DiscoveryIntegrityRecovery.jsx'

const INTEGRITY = {
  status: 'blocked',
  code: 'unexpected_scope_collapse',
  current_count: 37,
  baseline_count: 6970,
  baseline_scan_id: 'verified-123',
}

describe('DiscoveryIntegrityRecovery', () => {
  afterEach(() => { document.body.innerHTML = '' })

  it('renders only for the scope-collapse integrity condition', () => {
    expect(renderToStaticMarkup(<DiscoveryIntegrityRecovery integrity={null} />)).toBe('')
    expect(renderToStaticMarkup(
      <DiscoveryIntegrityRecovery integrity={{ status: 'blocked', code: 'another_check' }} />,
    )).toBe('')
  })

  it('shows the verified comparison and preserves the safety outcome', () => {
    const html = renderToStaticMarkup(
      <DiscoveryIntegrityRecovery integrity={INTEGRITY} source="drive" />,
    )
    expect(html).toContain('Discovery scope changed unexpectedly')
    expect(html).toContain('6,970')
    expect(html).toContain('37')
    expect(html).toContain('99.5% fewer')
    expect(html).toContain('last verified inventory remains unchanged')
    expect(html).toContain('No documents were assessed, remediated, or written back')
    expect(html).toContain('verified-123')
  })

  it('routes every recovery control through its supplied action', async () => {
    const actions = {
      reconnect: vi.fn(), review: vi.fn(), retry: vi.fn(), live: vi.fn(),
    }
    const host = document.createElement('div')
    document.body.appendChild(host)
    const root = createRoot(host)
    await act(async () => {
      root.render(<DiscoveryIntegrityRecovery integrity={INTEGRITY} source="sharepoint"
        onReconnect={actions.reconnect} onReviewScope={actions.review}
        onRetry={actions.retry} onViewLiveOps={actions.live} />)
    })
    expect(host.textContent).toContain('Reconnect SharePoint')
    for (const button of host.querySelectorAll('button')) {
      await act(async () => { button.click() })
    }
    Object.values(actions).forEach((action) => expect(action).toHaveBeenCalledOnce())
    await act(async () => { root.unmount() })
  })
})

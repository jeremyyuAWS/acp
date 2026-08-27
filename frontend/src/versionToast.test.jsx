import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import VersionToast, { VersionToastBanner } from './VersionToast.jsx'

// VersionToast: polls /config every 10 min and shows a reload banner when the server
// version advances past what the page loaded with. Polling is timer-driven and cannot
// be exercised with renderToStaticMarkup; we test the initial-state (hidden) and the
// banner UI (VersionToastBanner) which renders unconditionally.

describe('VersionToast initial state', () => {
  it('renders nothing by default (update not yet detected)', () => {
    const html = renderToStaticMarkup(createElement(VersionToast, { currentVersion: '2026.8.25.1' }))
    expect(html).toBe('')
  })

  it('renders nothing when currentVersion is null (config not loaded yet)', () => {
    const html = renderToStaticMarkup(createElement(VersionToast, { currentVersion: null }))
    expect(html).toBe('')
  })
})

describe('VersionToastBanner UI', () => {
  const noop = () => {}

  it('contains "new version of ACP is available" label', () => {
    const html = renderToStaticMarkup(createElement(VersionToastBanner, { onReload: noop, onDismiss: noop }))
    expect(html).toContain('new version of ACP is available')
  })

  it('has a Reload button', () => {
    const html = renderToStaticMarkup(createElement(VersionToastBanner, { onReload: noop, onDismiss: noop }))
    expect(html).toContain('Reload')
  })

  it('has a dismiss button with aria-label', () => {
    const html = renderToStaticMarkup(createElement(VersionToastBanner, { onReload: noop, onDismiss: noop }))
    expect(html).toContain('Dismiss version notification')
  })

  it('uses role="status" and aria-live="polite"', () => {
    const html = renderToStaticMarkup(createElement(VersionToastBanner, { onReload: noop, onDismiss: noop }))
    expect(html).toContain('role="status"')
    expect(html).toContain('aria-live="polite"')
  })

  it('is position fixed (does not displace content)', () => {
    const html = renderToStaticMarkup(createElement(VersionToastBanner, { onReload: noop, onDismiss: noop }))
    expect(html).toContain('position:fixed')
  })
})

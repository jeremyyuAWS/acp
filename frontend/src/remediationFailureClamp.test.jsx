import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import RemediationRunProgress from './RemediationRunProgress.jsx'

// The impossible number, and the guard that makes it unrenderable.
//
// Live 2026-09-04 (scan 8b83e9e1ca5c): a 147-document SharePoint batch failed, was submitted
// again, failed again, and the status endpoint — which counted every dead job the scan had ever
// produced — answered `failed: 294`. This component computed `done - failed` and printed
// "-147 documents remediated and verified."
//
// The counting fix is server-side (store.remediation_status now scopes to the batch). This is the
// last line of defence: no arrangement of upstream numbers may put a negative document count, or
// a failure count larger than the batch, in front of a user.
const batch = (over = {}) => ({
  total: 147, done: 147, failed: 294,
  metrics: { fixes: 0, verified: 0, stored: 0, failed: 294 },
  ...over,
})

describe('remediation summary clamps an over-counted failure total', () => {
  it('never renders a negative remediated count', () => {
    const html = renderToStaticMarkup(<RemediationRunProgress progress={batch()} />)
    expect(html).not.toContain('-147')
    expect(html).toContain('0 documents remediated and verified.')
  })

  it('caps the reported failures at the size of the batch', () => {
    const html = renderToStaticMarkup(<RemediationRunProgress progress={batch()} />)
    expect(html).not.toContain('294')
    expect(html).toContain('147 documents could not be remediated')
  })

  it('leaves an honest partial failure exactly as reported', () => {
    const html = renderToStaticMarkup(
      <RemediationRunProgress progress={batch({ failed: 12, metrics: { fixes: 40, verified: 130, stored: 135, failed: 12 } })} />)
    expect(html).toContain('135 documents remediated and verified.')
    expect(html).toContain('12 documents could not be remediated')
  })
})

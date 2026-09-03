import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import RemediationRunProgress from './RemediationRunProgress.jsx'

describe('RemediationRunProgress', () => {
  it('shows live automated-remediation progress from the SSE snapshot', () => {
    const html = renderToStaticMarkup(
      <RemediationRunProgress
        updateMode="live"
        progress={{ total: 20, done: 7, failed: 1, latest: 'report.docx',
                    activity: { text: 'Applying document language' } }} />,
    )
    expect(html).toContain('Automated remediation')
    expect(html).toContain('7 of 20 complete')
    expect(html).toContain('Remediation work queued')
    expect(html).toContain('Applied approved automatic fixes')
    expect(html).toContain('Re-checked corrected documents')
    expect(html).toContain('7 verified')
    expect(html).toContain('Recorded corrected copies')
    expect(html).toContain('Latest: report.docx')
    expect(html).toContain('Applying document language')
    expect(html).toContain('Processing now')
    expect(html).toContain('13 documents remaining')
    expect(html).toContain('Fix throughput')
    expect(html).toContain('1 document could not be remediated')
    expect(html).toContain('live')
    expect(html).toContain('aria-live="polite"')
  })

  it('does not render without a live progress snapshot', () => {
    expect(renderToStaticMarkup(<RemediationRunProgress progress={null} />)).toBe('')
  })

  it('keeps a completion summary visible after the stream drains', () => {
    const html = renderToStaticMarkup(
      <RemediationRunProgress progress={{ total: 20, done: 20, failed: 2, latest: 'report.docx' }} />,
    )
    expect(html).toContain('complete')
    expect(html).toContain('18 documents remediated and verified')
    expect(html).toContain('2 routed for attention')
    expect(html).not.toContain('Processing now')
  })
})

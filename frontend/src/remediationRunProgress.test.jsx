import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import RemediationRunProgress from './RemediationRunProgress.jsx'

describe('RemediationRunProgress', () => {
  it('keeps the SharePoint boundary visible while fixes run', () => {
    const html = renderToStaticMarkup(
      <RemediationRunProgress source="sharepoint"
        scope={{ kind: 'sharepoint', sites: [
          { id: 's1', name: 'Clinical', status: 'complete', libraries: [{ id: 'l1', name: 'Documents' }] },
        ] }} progress={{ total: 2, done: 1 }} />,
    )
    expect(html).toContain('Content source')
    expect(html).toContain('SharePoint')
    expect(html).toContain('Clinical')
    expect(html).toContain('1 document library')
  })

  it('shows live automated-remediation progress from the SSE snapshot', () => {
    const html = renderToStaticMarkup(
      <RemediationRunProgress
        updateMode="live"
        progress={{ total: 20, done: 7, failed: 1, latest: 'report.docx',
                    metrics: { fixes: 19, verified: 6, stored: 7, failed: 1 },
                    deltas: { fixes: 4, verified: 2, stored: 1, failed: 0 },
                    queued: 10, running: 3, workers: { active: 3, capacity: 5 },
                    byRule: [{ rule: '1.3.1', fixes: 12 }, { rule: '2.4.2', fixes: 7 }],
                    recentFiles: [{ file: 'saved.docx', at: '2026-09-04T12:00:00Z' }],
                    activity: { text: 'report.docx · 3.1.1 Language of Page · applying fix',
                                file: 'report.docx', sc: '3.1.1', sc_name: 'Language of Page',
                                action: 'applying fix', detail: 'setting document language', in_flight: 3 },
                    history: [
                      { at: 2, text: 'report.docx · 3.1.1 Language of Page · applying fix' },
                      { at: 1, text: 'slides.pptx · applying eligible WCAG fixes' },
                    ] }} />,
    )
    expect(html).toContain('Automated remediation')
    expect(html).toContain('7 of 20 complete')
    expect(html).toContain('Remediation work queued')
    expect(html).toContain('Applied approved automatic fixes')
    expect(html).toContain('Re-checked corrected documents')
    expect(html).toContain('6 verified')
    expect(html).toContain('Recorded corrected copies')
    expect(html).toContain('7 saved')
    expect(html).toContain('Fixes applied')
    expect(html).toContain('+4')
    expect(html).toContain('WCAG 1.3.1 · 12 fixes')
    expect(html).toContain('3 active')
    expect(html).toContain('2 standby')
    expect(html).toContain('10 queued')
    expect(html).toContain('saved.docx')
    expect(html).toContain('WCAG 3.1.1 · Language of Page')
    expect(html).toContain('applying fix')
    expect(html).toContain('setting document language')
    expect(html).toContain('3 files in parallel')
    expect(html).toContain('Recent remediation activity')
    expect(html).toContain('slides.pptx · applying eligible WCAG fixes')
    expect(html).toContain('Processing now')
    expect(html).toContain('13 documents remaining')
    expect(html).toContain('Remediation throughput')
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

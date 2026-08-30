import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

describe('loadPerf', () => {
  beforeEach(() => {
    performance.clearMarks()
    performance.clearMeasures()
    vi.spyOn(console, 'info').mockImplementation(() => {})
  })
  afterEach(() => {
    vi.restoreAllMocks()
    performance.clearMarks()
    performance.clearMeasures()
  })

  it('marks and measures a full bootstrap+scan load, logging one summary line', async () => {
    const { markLoad, logLoadSummary } = await import('./loadPerf.js')
    markLoad('load-start')
    markLoad('bootstrap-resolved')
    markLoad('scan-resolved')
    markLoad('load-complete')
    logLoadSummary({ hadPreview: true, hadScan: true })
    expect(console.info).toHaveBeenCalledTimes(1)
    const line = console.info.mock.calls[0][0]
    expect(line).toMatch(/^\[ACP load\] bootstrap \d+ms · scan \d+ms · total \d+ms · preview shown early$/)
  })

  it('omits the scan segment and says so when the workspace has no scan at all', async () => {
    const { markLoad, logLoadSummary } = await import('./loadPerf.js')
    markLoad('load-start')
    markLoad('bootstrap-resolved')
    markLoad('load-complete')
    logLoadSummary({ hadPreview: false, hadScan: false })
    const line = console.info.mock.calls[0][0]
    expect(line).toMatch(/^\[ACP load\] bootstrap \d+ms · total \d+ms · no cached preview$/)
  })

  it('logs nothing when the load never even reached load-start (defensive — should not happen)', async () => {
    const { logLoadSummary } = await import('./loadPerf.js')
    logLoadSummary({ hadPreview: false, hadScan: false })
    expect(console.info).not.toHaveBeenCalled()
  })

  it('shows "?ms" for a segment whose end mark is missing rather than throwing', async () => {
    // hadScan: true but 'scan-resolved' never got marked — e.g. getScan() rejected before
    // resolving. The summary must still print with whatever it can measure.
    const { markLoad, logLoadSummary } = await import('./loadPerf.js')
    markLoad('load-start')
    markLoad('bootstrap-resolved')
    markLoad('load-complete')
    expect(() => logLoadSummary({ hadPreview: false, hadScan: true })).not.toThrow()
    const line = console.info.mock.calls[0][0]
    expect(line).toContain('scan ?ms')
  })

  it('does not throw when performance.mark is unavailable', async () => {
    const original = performance.mark
    // @ts-ignore — simulate an environment without the Performance API
    delete performance.mark
    vi.resetModules()
    const { markLoad, logLoadSummary } = await import('./loadPerf.js')
    expect(() => { markLoad('load-start'); logLoadSummary({}) }).not.toThrow()
    performance.mark = original
    vi.resetModules()
  })
})

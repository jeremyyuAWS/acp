/**
 * GET /workspace/bootstrap wiring on the frontend (workspace-bootstrap redesign, Phase 1 —
 * backend: #960/#962). SIM mode and the pure overviewPreviewLine helper — both run with SIM ON
 * (the vitest default). The real (non-SIM) fetch path has its own file, workspaceBootstrapReal
 * .test.js, because vi.mock('./sim.js', ...) hoists to the top of whichever module calls it and
 * would otherwise flip SIM off for every test in this file too (see scanUnavailable.test.js for
 * the established convention this follows).
 */
import { describe, it, expect } from 'vitest'
import { overviewPreviewLine } from './EmptyState.jsx'

describe('overviewPreviewLine', () => {
  it('is null with no overview yet (bootstrap has not resolved, or no scan exists)', () => {
    expect(overviewPreviewLine(null)).toBeNull()
    expect(overviewPreviewLine(undefined)).toBeNull()
  })

  it('is null when the estate is empty — nothing to preview', () => {
    expect(overviewPreviewLine({ estate: { discovered: 0 }, documents: { certifiable: 5 } })).toBeNull()
    expect(overviewPreviewLine({ estate: {}, documents: {} })).toBeNull()
  })

  it('shows the document count alone when certifiable is not a number', () => {
    expect(overviewPreviewLine({ estate: { discovered: 42 }, documents: {} })).toBe('42 documents')
  })

  it('shows the certifiable percentage alongside the count', () => {
    expect(overviewPreviewLine({ estate: { discovered: 40 }, documents: { certifiable: 35 } }))
      .toBe('40 documents · 88% certifiable')
  })

  it('rounds, and handles 0% and 100% cleanly', () => {
    expect(overviewPreviewLine({ estate: { discovered: 10 }, documents: { certifiable: 0 } }))
      .toBe('10 documents · 0% certifiable')
    expect(overviewPreviewLine({ estate: { discovered: 10 }, documents: { certifiable: 10 } }))
      .toBe('10 documents · 100% certifiable')
  })
})

describe('api.js getWorkspaceBootstrap — SIM mode', () => {
  it('composes an equivalent shape from the existing SIM building blocks', async () => {
    const { getWorkspaceBootstrap } = await import('./api.js')
    const b = await getWorkspaceBootstrap()
    expect(typeof b.me.email).toBe('string')
    expect(b.scan_id).toBe('scan-cur')            // simListScans()[0] — the current, uncollapsed scan
    expect(b.scan_status).toBe('done')
    expect(b.revision).toBe(0)
    expect(b.overview.estate.discovered).toBeGreaterThan(0)
    expect(b.overview.documents.certifiable).toBeGreaterThanOrEqual(0)
    expect(Array.isArray(b.scans)).toBe(true)
    expect(b.scans[0].id).toBe('scan-cur')
    expect(b.active_job).toEqual({})
  })
})

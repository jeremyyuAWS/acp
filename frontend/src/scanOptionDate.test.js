import { describe, it, expect } from 'vitest'
import { scanOptionAt, scanWorkflowContext } from './scanOptionDate.js'

describe('scanOptionAt', () => {
  it('prefers completed_at when the scan was assessed', () => {
    expect(scanOptionAt({ completed_at: '2026-08-28T23:47:00Z', discovered_at: '2026-08-28T16:04:00Z' }))
      .toBe('2026-08-28T23:47:00Z')
  })

  it('falls back to discovered_at for an ADR 0020 Discover-only run', () => {
    expect(scanOptionAt({ completed_at: null, discovered_at: '2026-08-28T16:04:00Z' }))
      .toBe('2026-08-28T16:04:00Z')
  })

  it('never falls through to null-as-epoch — returns null explicitly when neither field is set', () => {
    expect(scanOptionAt({ completed_at: null, discovered_at: null })).toBeNull()
    expect(scanOptionAt({})).toBeNull()
  })

  it('returns null for a null/undefined scan entry rather than throwing', () => {
    expect(scanOptionAt(null)).toBeNull()
    expect(scanOptionAt(undefined)).toBeNull()
  })
})

describe('scanWorkflowContext', () => {
  it('names a linked workflow revision', () => {
    expect(scanWorkflowContext({ workflow_id: 'workflow-1', workflow_revision: 3 }))
      .toBe('Workflow revision 3')
  })

  it('does not invent lineage for legacy scans', () => {
    expect(scanWorkflowContext({ workflow_revision: 1 })).toBe('')
  })
})

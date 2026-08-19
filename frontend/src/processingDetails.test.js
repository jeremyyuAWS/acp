// The live "Processing details" data model (progress redesign, slice 3): per-file rows + filters,
// fed by the file_records get_scan streams as each file lands.
import { describe, it, expect } from 'vitest'
import { processingRows, filterRows, filterCounts, PROCESSING_FILTERS } from './processingDetails.js'

const FILES = [
  { file: 'Policy.docx', status: 'certifiable', score: 98 },
  { file: 'Report.pdf', status: 'uncertain', score: 72 },
  { file: 'Old.pptx', status: 'error', score: null },
  { file: 'Pending.xlsx', status: 'discovered', score: null },
]

describe('processingRows', () => {
  it('maps status to a human result + semantic kind, and format from the filename', () => {
    const rows = processingRows(FILES)
    expect(rows[0]).toMatchObject({ file: 'Policy.docx', format: 'DOCX', result: 'Passed', kind: 'ok', score: 98 })
    expect(rows[1]).toMatchObject({ format: 'PDF', result: 'Needs review', kind: 'warn' })
    expect(rows[2]).toMatchObject({ format: 'PPTX', result: 'Failed', kind: 'bad', score: null })
    expect(rows[3]).toMatchObject({ result: 'Queued', kind: 'muted' })
  })

  it('is safe on empty / missing input', () => {
    expect(processingRows(undefined)).toEqual([])
  })
})

describe('filters', () => {
  const rows = processingRows(FILES)

  it('findings shows need-review, failed shows errors, completed drops the discovered placeholder', () => {
    expect(filterRows(rows, 'findings').map((r) => r.file)).toEqual(['Report.pdf'])
    expect(filterRows(rows, 'failed').map((r) => r.file)).toEqual(['Old.pptx'])
    expect(filterRows(rows, 'completed').map((r) => r.file)).toEqual(['Policy.docx', 'Report.pdf', 'Old.pptx'])
    expect(filterRows(rows, 'all')).toHaveLength(4)
  })

  it('an unknown filter key falls back to all rather than hiding everything', () => {
    expect(filterRows(rows, 'nonsense')).toHaveLength(4)
  })

  it('precomputes counts for every tab', () => {
    expect(filterCounts(rows)).toEqual({ all: 4, findings: 1, failed: 1, completed: 3 })
    expect(PROCESSING_FILTERS.map((f) => f.key)).toEqual(['all', 'findings', 'failed', 'completed'])
  })
})

import { describe, it, expect } from 'vitest'
import { contentTypeBreakdown, hasContentTypeData } from './contentTypeBreakdown.js'

// SharePoint's Content Type, surfaced when the source actually returns one.
//
// Best-effort and NOT the department/tag classification classificationData.js gates — a real
// SharePoint column, named whatever a library's own convention calls it, not the same axis as
// "which department owns this" or "is this under legal hold". Conflating the two would be exactly
// the invention this codebase spent tonight removing.

const row = (content_type) => ({ file: `f-${Math.random()}.docx`, content_type })

describe('whether the source returned anything at all', () => {
  it('is false when no row carries one — Drive, local, or a tenant that never fires the read', () => {
    expect(hasContentTypeData([row(undefined), row(null), row('')])).toBe(false)
    expect(hasContentTypeData([])).toBe(false)
    expect(hasContentTypeData(null)).toBe(false)
  })

  it('is true the moment ONE row carries one', () => {
    expect(hasContentTypeData([row(undefined), row('Policy')])).toBe(true)
  })
})

describe('the breakdown', () => {
  it('returns null over an estate the feature never touched', () => {
    // The panel this feeds must not chart one grey "not returned" bar over an estate where
    // content-type enrichment never fired — that would read as a measurement, not an absence.
    expect(contentTypeBreakdown([row(undefined), row(undefined)])).toBe(null)
  })

  it('groups by content type, biggest first, and reconciles to the file count', () => {
    const files = [row('Policy'), row('Policy'), row('Contract'), row(undefined)]
    const b = contentTypeBreakdown(files)
    expect(b.balanced).toBe(true)
    expect(b.total).toBe(4)
    expect(b.buckets.map((x) => x.label)).toEqual(['Policy', 'Contract', 'Not returned by the source'])
    expect(b.buckets[0].count).toBe(2)
  })

  it('the "not returned" bucket is real, marked, and sorted last regardless of size', () => {
    // Grey, and last — it is the gap in the source's answer, not a category the library defined,
    // even when it happens to be the biggest bucket.
    const files = [row('Policy'), row(undefined), row(undefined), row(undefined)]
    const b = contentTypeBreakdown(files)
    const last = b.buckets[b.buckets.length - 1]
    expect(last.label).toBe('Not returned by the source')
    expect(last.known).toBe(false)
    expect(last.count).toBe(3)
    expect(b.buckets[0].known).toBe(true)
  })

  it('never drops a row — every file lands in exactly one bucket', () => {
    const files = [row('Policy'), row(''), row('  '), row(null)]
    const b = contentTypeBreakdown(files)
    expect(b.sum).toBe(4)
    expect(b.balanced).toBe(true)
  })
})

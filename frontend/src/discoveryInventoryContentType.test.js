import { describe, it, expect } from 'vitest'
import { lifecycleIndex, mergeLifecycle } from './discoveryInventory.js'

// content_type rides the same paginated inventory read lifecycle_status does — but the two must
// merge INDEPENDENTLY, because they come from different sources (a rule pass vs. a Graph read)
// and can arrive apart.
//
// THE BUG THIS FIXES. mergeLifecycle used to bail out of the WHOLE merge whenever a row's
// lifecycle_status was null — which is exactly the same-shaped mistake this codebase already
// caught once tonight for a different field: a row with a real content type and no lifecycle rule
// match would have LOST its content type here, for a reason that had nothing to do with content
// type.

const INV = (rows) => ({ rows, total: rows.length })

describe('lifecycleIndex carries content_type alongside the lifecycle fields', () => {
  it('reads it off the row, defaulting to null', () => {
    const idx = lifecycleIndex([{ file: 'a.docx', content_type: 'Policy' }, { file: 'b.docx' }])
    expect(idx.get('a.docx').content_type).toBe('Policy')
    expect(idx.get('b.docx').content_type).toBe(null)
  })
})

describe('mergeLifecycle applies the two fields independently', () => {
  it('content_type survives a row with NO lifecycle_status', () => {
    const files = [{ file: 'a.docx' }]
    const inv = INV([{ file: 'a.docx', content_type: 'Policy', lifecycle_status: null }])
    const merged = mergeLifecycle(files, inv)
    expect(merged[0].content_type).toBe('Policy')
    expect(merged[0].lifecycle_status).toBeUndefined()
  })

  it('lifecycle_status survives a row with NO content_type', () => {
    const files = [{ file: 'a.docx' }]
    const inv = INV([{ file: 'a.docx', lifecycle_status: 'Archive Candidate', content_type: null }])
    const merged = mergeLifecycle(files, inv)
    expect(merged[0].lifecycle_status).toBe('Archive Candidate')
    expect(merged[0].content_type).toBeUndefined()
  })

  it('both merge together when both are present', () => {
    const files = [{ file: 'a.docx' }]
    const inv = INV([{ file: 'a.docx', lifecycle_status: 'Active', content_type: 'Contract' }])
    const merged = mergeLifecycle(files, inv)
    expect(merged[0].lifecycle_status).toBe('Active')
    expect(merged[0].content_type).toBe('Contract')
  })

  it('neither is invented for a file the inventory never mentions', () => {
    const files = [{ file: 'a.docx' }, { file: 'never-listed.docx' }]
    const inv = INV([{ file: 'a.docx', lifecycle_status: 'Active', content_type: 'Contract' }])
    const merged = mergeLifecycle(files, inv)
    expect(merged[1].lifecycle_status).toBeUndefined()
    expect(merged[1].content_type).toBeUndefined()
  })
})

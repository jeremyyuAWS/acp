/**
 * Reading the paginated discover inventory — completely, or not at all.
 *
 * The case these exist for is the partial read. `GET /scans/{id}/inventory` caps at 1000 rows a
 * page, so a caller that reads page one and counts over it gets a number that is correct about
 * the page and false about the estate — and it arrives as a small, reassuring figure nobody
 * questions. Every incomplete outcome here must be `null`, which the screen renders as nothing.
 */
import { describe, it, expect } from 'vitest'
import {
  MAX_PAGES, PAGE_LIMIT, lifecycleIndex, loadDiscoveryInventory, mergeLifecycle,
} from './discoveryInventory.js'

const row = (file, extra = {}) => ({ file, path: file, lifecycle_status: 'Active', ...extra })
const arch = (file) => row(file, {
  lifecycle_status: 'Archive Candidate', lifecycle_rule_id: 'p1',
  lifecycle_reason: "matched archive rule 'Legacy clinical policies'",
})

/** A route stub that pages a fixed row list the way the real one does. */
const pager = (rows, { limit = PAGE_LIMIT, total = rows.length } = {}) => {
  const calls = []
  const fn = (scanId, { offset, limit: l } = {}) => {
    calls.push({ scanId, offset, limit: l })
    return Promise.resolve({ scan_id: scanId, total, offset, limit: l,
                             rows: rows.slice(offset, offset + Math.min(l, limit)) })
  }
  fn.calls = calls
  return fn
}

describe('a complete read returns every row the route says exists', () => {
  it('reads a single page when the estate fits in one', async () => {
    const fetchPage = pager([row('a.docx'), arch('b.pdf')])
    const inv = await loadDiscoveryInventory('s1', fetchPage)
    expect(inv.total).toBe(2)
    expect(inv.rows).toHaveLength(2)
    expect(fetchPage.calls).toHaveLength(1)
    expect(fetchPage.calls[0]).toMatchObject({ scanId: 's1', offset: 0, limit: PAGE_LIMIT })
  })

  it('pages until it has the whole population, advancing the offset each time', async () => {
    const rows = Array.from({ length: 25 }, (_, i) => row(`f${i}.docx`))
    const inv = await loadDiscoveryInventory('s1', pager(rows), { limit: 10 })
    expect(inv.total).toBe(25)
    expect(inv.rows.map((r) => r.file)).toEqual(rows.map((r) => r.file))
  })

  it('asks for offsets that follow what it already has', async () => {
    const fetchPage = pager(Array.from({ length: 25 }, (_, i) => row(`f${i}.docx`)))
    await loadDiscoveryInventory('s1', fetchPage, { limit: 10 })
    expect(fetchPage.calls.map((c) => c.offset)).toEqual([0, 10, 20])
  })

  it('handles a genuinely empty estate as a complete read of nothing', async () => {
    const inv = await loadDiscoveryInventory('s1', pager([]))
    expect(inv).toEqual({ rows: [], total: 0 })
  })
})

describe('every incomplete outcome is null — never a partial answer', () => {
  it('is null when the route rejects (network, auth, a scan for another account)', async () => {
    expect(await loadDiscoveryInventory('s1', () => Promise.reject(new Error('HTTP 403')))).toBeNull()
  })

  it('is null when the route stops returning rows it still owes', async () => {
    // The truncated read: total says 5,000, the route hands back an empty page. Returning the
    // rows collected so far would be the count-without-its-population defect.
    const short = () => Promise.resolve({ total: 5000, rows: [] })
    expect(await loadDiscoveryInventory('s1', short)).toBeNull()
  })

  it('is null when the population moves under it mid-read', async () => {
    let n = 0
    const shifting = (sid, { offset }) => Promise.resolve({
      total: n++ === 0 ? 30 : 40, offset, rows: [row(`f${offset}.docx`)],
    })
    expect(await loadDiscoveryInventory('s1', shifting, { limit: 1 })).toBeNull()
  })

  it('is null when the response is malformed or carries no usable total', async () => {
    expect(await loadDiscoveryInventory('s1', () => Promise.resolve(null))).toBeNull()
    expect(await loadDiscoveryInventory('s1', () => Promise.resolve({ total: 2 }))).toBeNull()
    expect(await loadDiscoveryInventory('s1', () => Promise.resolve({ rows: [] }))).toBeNull()
    expect(await loadDiscoveryInventory('s1', () => Promise.resolve({ rows: [], total: -1 }))).toBeNull()
  })

  it('gives up rather than page forever, and says so with null', async () => {
    const rows = Array.from({ length: MAX_PAGES + 5 }, (_, i) => row(`f${i}.docx`))
    expect(await loadDiscoveryInventory('s1', pager(rows), { limit: 1 })).toBeNull()
  })

  it('is null without a scan id or a fetcher — nothing was asked, so nothing is claimed', async () => {
    expect(await loadDiscoveryInventory(null, pager([row('a.docx')]))).toBeNull()
    expect(await loadDiscoveryInventory('s1', undefined)).toBeNull()
  })
})

describe('merging the lifecycle columns onto the scan file rows', () => {
  const files = [{ file: 'a.docx' }, { file: 'b.pdf' }]

  it('attaches the recorded status, rule and reason', async () => {
    const inv = await loadDiscoveryInventory('s1', pager([row('a.docx'), arch('b.pdf')]))
    const merged = mergeLifecycle(files, inv)
    expect(merged[0].lifecycle_status).toBe('Active')
    expect(merged[1]).toMatchObject({
      lifecycle_status: 'Archive Candidate', lifecycle_rule_id: 'p1',
      lifecycle_reason: "matched archive rule 'Legacy clinical policies'",
    })
  })

  it('passes the file rows straight through when the read failed — the same object, untouched', () => {
    // This is the guard that keeps a failed read from rendering as "0 tagged for archive review":
    // un-merged rows carry no lifecycle field, so hasLifecycleData stays false downstream.
    expect(mergeLifecycle(files, null)).toBe(files)
    expect(mergeLifecycle(files, { rows: [] })).toBe(files)
    expect(mergeLifecycle(files, { rows: null })).toBe(files)
  })

  it('leaves a file the inventory did not cover WITHOUT a status, rather than calling it Active', async () => {
    const inv = await loadDiscoveryInventory('s1', pager([arch('a.docx')]))
    const merged = mergeLifecycle([{ file: 'a.docx' }, { file: 'unlisted.pdf' }], inv)
    expect(merged[0].lifecycle_status).toBe('Archive Candidate')
    expect(merged[1].lifecycle_status).toBeUndefined()
  })

  it('does not overwrite a path the scan row already carries', async () => {
    const inv = await loadDiscoveryInventory('s1', pager([row('a.docx', { path: 'Inventory/a.docx' })]))
    expect(mergeLifecycle([{ file: 'a.docx', path: 'Scan/a.docx' }], inv)[0].path).toBe('Scan/a.docx')
    expect(mergeLifecycle([{ file: 'a.docx' }], inv)[0].path).toBe('Inventory/a.docx')
  })

  it('indexes by filename and ignores rows with no file', () => {
    const idx = lifecycleIndex([arch('a.docx'), null, { lifecycle_status: 'Active' }])
    expect([...idx.keys()]).toEqual(['a.docx'])
  })

  it('merges a recorded override (lifecycle rules #8) INDEPENDENTLY of lifecycle_status, same as content_type', async () => {
    const overridden = row('a.docx', {
      lifecycle_status: 'Archive Candidate', lifecycle_rule_id: 'p1',
      lifecycle_reason: "matched archive rule 'Legacy clinical policies'",
      lifecycle_override_reason: 'still needed for the audit',
      lifecycle_overridden_by: 'reviewer@x.com',
      lifecycle_overridden_at: '2026-08-21T10:00:00+00:00',
    })
    const inv = await loadDiscoveryInventory('s1', pager([overridden]))
    const merged = mergeLifecycle([{ file: 'a.docx' }], inv)[0]
    expect(merged.lifecycle_override_reason).toBe('still needed for the audit')
    expect(merged.lifecycle_overridden_by).toBe('reviewer@x.com')
    expect(merged.lifecycle_status).toBe('Archive Candidate')   // both facts arrived, independently
  })

  it('leaves override fields absent on a row nobody overrode, rather than null-flooding every row', async () => {
    const inv = await loadDiscoveryInventory('s1', pager([arch('a.docx')]))
    const merged = mergeLifecycle([{ file: 'a.docx' }], inv)[0]
    expect(merged.lifecycle_override_reason).toBeUndefined()
    expect('lifecycle_overridden_by' in merged).toBe(false)
  })
})

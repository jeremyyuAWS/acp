import { describe, it, expect, vi, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// fileURLToPath, not `new URL(..., import.meta.url)`: under vitest import.meta.url is not a
// file: URL, and readFileSync rejects it with "The URL must be of scheme file". This is the
// pattern the other v2 source-level tests already use.
const HERE = dirname(fileURLToPath(import.meta.url))
const source = () => readFileSync(join(HERE, 'SharePoint.jsx'), 'utf8')

// SharePoint's "↑ SharePoint" button does a destructive in-place PUT, exactly as Drive's does.
// Drive copies the original into _mova-originals/<date>/ first. SharePoint did not — so a save
// there replaced the user's file with no way back, and nothing on screen said so.
//
// The difference from Drive is deliberate and is the point of these tests: Drive's archive is
// best-effort (`catch { /* archive best-effort */ }`), so a failed archive is followed by the
// overwrite anyway. An archive that only sometimes happens is not a backup, and it fails
// invisibly precisely when it matters. Here a failed archive ABORTS the save.

const { spArchiveOriginal } = await import('./SharePoint.jsx')

afterEach(() => { vi.restoreAllMocks() })

const ok = (payload) => ({ ok: true, status: 200, json: async () => payload })
const err = (status) => ({ ok: false, status, json: async () => ({}) })

function stub(handlers) {
  const seen = []
  global.fetch = vi.fn(async (url, opts = {}) => {
    seen.push({ url, method: opts.method || 'GET' })
    for (const [match, resp] of handlers) {
      if (url.includes(match) && (!resp.method || resp.method === (opts.method || 'GET'))) {
        return resp.value
      }
    }
    return ok({ value: [] })
  })
  return seen
}

describe('spArchiveOriginal', () => {
  it('copies the original into a dated folder under _mova-originals', async () => {
    const seen = stub([
      ['/root/children', { method: 'GET', value: ok({ value: [{ id: 'ORIG', name: '_mova-originals', folder: {} }] }) }],
      ['/items/ORIG/children', { method: 'GET', value: ok({ value: [{ id: 'DATED', name: new Date().toISOString().slice(0, 10), folder: {} }] }) }],
      ['/copy', { method: 'POST', value: ok({ id: 'copied' }) }],
    ])
    await spArchiveOriginal('tok', 'd1', 'i1')
    const copy = seen.find((s) => s.url.includes('/copy'))
    expect(copy, 'no copy was issued — the original would be overwritten unbacked').toBeTruthy()
    expect(copy.url).toContain('/drives/d1/items/i1/copy')
  })

  it('falls back to /me/drive when the item has no drive id', async () => {
    // An item listed before site support carries no driveId; it lives in the user's OneDrive.
    const seen = stub([
      ['/root/children', { method: 'GET', value: ok({ value: [{ id: 'ORIG', name: '_mova-originals', folder: {} }] }) }],
      ['/items/ORIG/children', { method: 'GET', value: ok({ value: [{ id: 'DATED', name: new Date().toISOString().slice(0, 10), folder: {} }] }) }],
      ['/copy', { method: 'POST', value: ok({}) }],
    ])
    await spArchiveOriginal('tok', null, 'i1')
    expect(seen.find((s) => s.url.includes('/copy')).url).toContain('/me/drive/items/i1/copy')
  })

  it('throws when the copy fails, so the caller does not overwrite', async () => {
    stub([
      ['/root/children', { method: 'GET', value: ok({ value: [{ id: 'ORIG', name: '_mova-originals', folder: {} }] }) }],
      ['/items/ORIG/children', { method: 'GET', value: ok({ value: [{ id: 'DATED', name: new Date().toISOString().slice(0, 10), folder: {} }] }) }],
      ['/copy', { method: 'POST', value: err(507) }],
    ])
    await expect(spArchiveOriginal('tok', 'd1', 'i1')).rejects.toThrow(/archive failed/)
  })

  it('reuses an existing _mova-originals rather than creating a second one', async () => {
    // Creating unconditionally is how Drive grew duplicate mirror folders, and on an ARCHIVE
    // folder a second one means half the backups are somewhere nobody looks.
    const seen = stub([
      ['/root/children', { method: 'GET', value: ok({ value: [{ id: 'ORIG', name: '_mova-originals', folder: {} }] }) }],
      ['/items/ORIG/children', { method: 'GET', value: ok({ value: [{ id: 'DATED', name: new Date().toISOString().slice(0, 10), folder: {} }] }) }],
      ['/copy', { method: 'POST', value: ok({}) }],
    ])
    await spArchiveOriginal('tok', 'd1', 'i1')
    const creates = seen.filter((s) => s.method === 'POST' && s.url.includes('children'))
    expect(creates, 'created a folder that already existed').toHaveLength(0)
  })

  it('never asks Graph to replace an existing folder', async () => {
    // `conflictBehavior: replace` on _mova-originals would clobber the archive itself — the one
    // outcome this whole path exists to prevent.
    const src = source()
    expect(src).not.toMatch(/conflictBehavior'?\s*:\s*'replace'/)
    expect(src).toMatch(/conflictBehavior'\]?\s*:\s*'fail'/)
  })
})

describe('the save path', () => {
  it('archives before it overwrites, and does not swallow the failure', async () => {
    const src = source()
    const archive = src.indexOf('await spArchiveOriginal(')
    const put = src.indexOf("method: 'PUT'")
    expect(archive).toBeGreaterThan(-1)
    expect(archive, 'the overwrite runs before the backup').toBeLessThan(put)
    // Drive wraps its archive in a catch; SharePoint deliberately must not.
    expect(src).not.toMatch(/spArchiveOriginal\([^)]*\)\s*\.catch/)
  })

  it('tells the user what the confirmation actually does', async () => {
    const src = source()
    expect(src).toContain('_mova-originals')
    expect(src).toMatch(/Replace in SharePoint\? Original is copied/)
  })
})

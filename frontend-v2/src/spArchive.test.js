import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// SharePoint's "↑ SharePoint" button did a destructive in-place PUT straight to Graph from the
// browser, with its own archive-first copy alongside it.
//
// This file used to test that browser-side archive (spArchiveOriginal). The archive did not go
// away — it moved to scanner._sp_archive_original, where it is tested end-to-end against the
// route in tests/test_sharepoint_writeback.py, including the ordering and the fail-closed
// behaviour that were the point of the original tests. Keeping a duplicate here would be a
// second implementation to maintain; what is worth pinning on this side is that the button
// stopped writing to Graph itself, because that is the thing a future edit could quietly undo.
//
// Source-level: this asserts which HTTP call a component makes, and a mounted test that stubbed
// fetch would pass just as happily with the direct Graph PUT restored beside the route call.

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

const button = () => {
  const s = read('SharePoint.jsx')
  const start = s.indexOf('export function SpUploadButton')
  const end = s.indexOf('// ── Main SharePoint component')
  expect(start, 'SpUploadButton not found').toBeGreaterThan(-1)
  expect(end, 'component boundary not found').toBeGreaterThan(start)
  return s.slice(start, end)
}

describe('the SharePoint write-back button', () => {
  it('writes through the server route, not straight to Graph', () => {
    expect(button()).toMatch(/await uploadToSharePoint\(/)
    expect(read('SharePoint.jsx')).toContain("import { uploadToSharePoint } from './api.js'")
  })

  it('makes no Graph call of its own', () => {
    // The specific regression: a PUT to /items/<id>/content re-added beside the route call would
    // overwrite the file WITHOUT the server's archive in front of it.
    const b = button()
    expect(b).not.toMatch(/method:\s*'PUT'/)
    expect(b).not.toMatch(/method:\s*'PATCH'/)
    expect(b).not.toMatch(/GRAPH/)
    expect(b, 'still reading the token to call Graph directly').not.toMatch(/sessionStorage/)
  })

  it('passes item_id, which is what selects replace-in-place', () => {
    // Without itemId the route writes a COPY into the mirror folder instead — same endpoint,
    // silently different outcome, and the confirmation below would then be a lie.
    expect(button()).toMatch(/uploadToSharePoint\(\{[^}]*itemId[^}]*\}\)/)
  })

  it('still tells the user what the confirmation actually does', () => {
    expect(button()).toMatch(/Replace in SharePoint\? Original is copied/)
    expect(button()).toContain('_mova-originals')
  })

  it('surfaces the server error instead of flattening it to "Reconnect"', () => {
    // Graph refuses a write with a 403 the route translates into the CONSENT that would fix it.
    // "Reconnect SharePoint" sent people to re-authenticate when the fix was a tenant-admin
    // grant they could not make themselves.
    const b = button()
    expect(b).toMatch(/setErrMsg\(e\?\.message/)
    expect(b).not.toMatch(/setErrMsg\('Reconnect SharePoint'\)/)
  })

  it('no longer ships the browser-side archive helpers', () => {
    // Dead code that still looks callable is how a later edit reintroduces the direct write.
    const s = read('SharePoint.jsx')
    expect(s).not.toContain('spArchiveOriginal')
    expect(s).not.toMatch(/async function spFolder\(/)
  })
})

describe('the upload client', () => {
  const api = () => {
    const s = read('api.js')
    return s.slice(s.indexOf('export const uploadToSharePoint'), s.indexOf('export const queueHitlVerify'))
  }

  it('sends item_id only when replacing', () => {
    expect(api()).toMatch(/if \(itemId\) form\.append\('item_id', itemId\)/)
  })

  it('requires a drive id for a MIRROR write and not for a replace', () => {
    // An item listed from OneDrive carries no driveId at all (scanner._sp_list), and the server
    // resolves that to /me/drive exactly as the download path always has. Demanding one here
    // would break every OneDrive write-back while reading like a safety check.
    expect(api()).toMatch(/if \(!driveId && !itemId\)/)
    expect(api()).toMatch(/if \(driveId\) form\.append\('drive_id', driveId\)/)
  })
})

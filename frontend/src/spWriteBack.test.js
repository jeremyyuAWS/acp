import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// This SPA's "↑ SharePoint" button replaced the user's file in place with NO backup of any kind:
// a PUT of the remediated bytes straight over the original item. A wrong remediation, a wrong
// file in the queue, or a truncated blob and the original was gone — and the confirmation read
// only "Replace in SharePoint?", so nobody who agreed to it was agreeing to that. Drive's button
// in this same file has archived to _mova-originals since it shipped; only SharePoint was
// unprotected.
//
// It now goes through /sharepoint/upload with item_id, where the server archives first and
// ABORTS the write if the archive fails. The archive is NOT reimplemented in the browser: one
// copy of a safety-critical path, whose failure mode is the second copy quietly losing its
// fail-closed behaviour while the first keeps it. That behaviour is tested against the route in
// tests/test_sharepoint_writeback.py.
//
// Source-level, because what matters is WHICH request the component makes. A mounted test with
// fetch stubbed would pass just as happily with the direct Graph PUT restored beside the route
// call — which is precisely the regression that would cost someone a document.

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
  it('writes through the server route', () => {
    expect(button()).toMatch(/await uploadToSharePoint\(/)
    expect(read('SharePoint.jsx')).toContain("import { uploadToSharePoint } from './api.js'")
  })

  it('makes no Graph call of its own', () => {
    // THE regression to guard. A PUT to /items/<id>/content re-added here overwrites the file
    // with no archive in front of it, and nothing about the button would look different.
    const b = button()
    expect(b, 'a direct PUT is back — this overwrites with no backup').not.toMatch(/method:\s*'PUT'/)
    expect(b).not.toMatch(/method:\s*'PATCH'/)
    expect(b).not.toMatch(/GRAPH/)
    expect(b, 'still reading the token to call Graph directly').not.toMatch(/sessionStorage/)
  })

  it('passes item_id, which is what selects replace-in-place', () => {
    // Without it the route writes a COPY into the mirror folder instead — same endpoint,
    // silently different outcome, and the confirmation below would then be false.
    expect(button()).toMatch(/uploadToSharePoint\(\{[^}]*itemId[^}]*\}\)/)
  })

  it('tells the user the original is kept', () => {
    // The old copy asked for consent to a replace and did not mention that nothing was saved
    // first, because nothing was.
    expect(button()).toMatch(/Replace in SharePoint\? Original is copied/)
    expect(button()).toContain('_mova-originals')
  })

  it('surfaces the server error instead of flattening it to "Reconnect"', () => {
    const b = button()
    expect(b).toMatch(/setErrMsg\(e\?\.message/)
    expect(b).not.toMatch(/setErrMsg\('Reconnect SharePoint'\)/)
  })
})

describe('the upload client', () => {
  const api = () => {
    const s = read('api.js')
    const i = s.indexOf('export const uploadToSharePoint')
    expect(i, 'uploadToSharePoint is missing').toBeGreaterThan(-1)
    return s.slice(i, s.indexOf('export const', i + 10))
  }

  it('refuses without an item id rather than writing somewhere', () => {
    expect(api()).toMatch(/if \(!itemId\) return Promise\.reject/)
  })

  it('always sends item_id, and drive_id only when known', () => {
    // An item listed from OneDrive carries no driveId; the server resolves that to /me/drive,
    // as the download path does for the same items.
    expect(api()).toMatch(/fd\.append\('item_id', itemId\)/)
    expect(api()).toMatch(/if \(driveId\) fd\.append\('drive_id', driveId\)/)
  })

  it('does not set Content-Type on the multipart body', () => {
    // The browser sets multipart/form-data WITH the boundary. Setting it by hand omits the
    // boundary and the server cannot parse the body — a failure that reads as a server bug.
    const a = api()
    expect(a).toMatch(/new FormData\(\)/)
    expect(a).not.toMatch(/'Content-Type':/)
  })

  it('refuses in SIM rather than reporting a write that never happened', () => {
    // This button's whole claim is that a real file was replaced. A demo build answering
    // "✓ Saved to SharePoint" for a write that never left the browser is the one lie here a
    // viewer would act on.
    expect(api()).toMatch(/if \(SIM\) return Promise\.reject/)
  })
})

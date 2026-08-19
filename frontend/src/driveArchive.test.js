import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Drive's archive-before-overwrite was described as "best-effort". It was weaker than that.
//
// Four separate defects, each of which alone makes the backup worthless:
//
//   1. OFF BY DEFAULT. `localStorage.getItem(LS_ARCHIVE) === 'true'` — an unset key is null, so
//      the shipped behaviour for anyone who had not found a checkbox was a destructive in-place
//      overwrite with no backup at all.
//   2. THE COPY RESPONSE WAS NEVER CHECKED. `await fetch(.../copy)` with no `.ok` test, so a 403
//      (no write scope), a 507 (quota) or a 404 (file moved) all resolved as success.
//   3. NEITHER WERE THE FOLDER CALLS. A failed lookup fell through to create; a failed create
//      returned `undefined`; the copy was then issued with `parents: [undefined]`. Three
//      unchecked responses in a row, and all three failing looked exactly like success.
//   4. `catch { /* archive best-effort */ }` swallowed whatever did throw, and the overwrite ran.
//
// And the BULK path in Upload.jsx was worse still: it inlined its own archive around
// `await import('./GoogleDrive.jsx')` destructuring `findOrCreateFolder`, which that module never
// exported. `fof` was always undefined, the `if (fof)` guard always false — so the bulk archive
// never ran once, for anybody, ticked or not, while the loop overwrote every file.
//
// Source-level, and COMMENT-STRIPPED. The explanation above quotes the old code, and a naive
// substring assertion would match the prose and pass with the defect restored. That has bitten
// this repo twice; the fix both times was to assert against code lines only.

const HERE = dirname(fileURLToPath(import.meta.url))
const code = (f) => readFileSync(join(HERE, f), 'utf8')
  .split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')

describe('archiveOriginal fails closed', () => {
  it('checks the copy response', () => {
    expect(code('GoogleDrive.jsx')).toMatch(/if \(!r\.ok\) throw new Error\('archive failed/)
  })

  it('checks both folder calls, and the id that comes back', () => {
    const s = code('GoogleDrive.jsx')
    expect(s).toMatch(/if \(!r\.ok\) throw new Error\('could not look for/)
    expect(s).toMatch(/if \(!cr\.ok\) throw new Error\('could not create/)
    expect(s, 'a created folder with no id yields parents: [undefined]').toMatch(/if \(!f\.id\) throw/)
  })

  it('is exported, so no caller has to rebuild it', () => {
    // The bulk path rebuilt it and got it wrong. One implementation.
    expect(code('GoogleDrive.jsx')).toMatch(/export async function archiveOriginal/)
  })
})

describe('the single-file save', () => {
  it('archives unconditionally', () => {
    // An opt-out backup on a write that cannot be undone is the same defect wearing a
    // preference. Nobody who left the box unticked was choosing "and discard the original".
    const s = code('GoogleDrive.jsx')
    expect(s).not.toMatch(/LS_ARCHIVE/)
    expect(s).not.toMatch(/mova_drive_archive/)
  })

  it('aborts the overwrite when the archive fails', () => {
    // THE regression. `catch { }` here means the file is replaced with no backup.
    const s = code('GoogleDrive.jsx')
    expect(s).not.toMatch(/catch \{ ?\/\* archive best-effort \*\/ ?\}/)
    expect(s).toMatch(/setErrMsg\(e\.message \|\| 'Could not back up/)
  })

  it('says the original is kept, because now it always is', () => {
    expect(code('GoogleDrive.jsx')).toContain('Original is copied to _mova-originals first')
  })
})

describe('the bulk save', () => {
  it('uses the shared archive rather than inlining one', () => {
    const s = code('Upload.jsx')
    expect(s).toMatch(/await archiveOriginal\(token, item\.driveFileId\)/)
    expect(s, 'the dynamic import of a never-exported symbol is back').not.toContain('findOrCreateFolder: fof')
  })

  it('skips a file whose archive failed instead of overwriting it', () => {
    // Skip, not abort: one bad file must not stop the other forty, and must not be replaced
    // either.
    expect(code('Upload.jsx')).toMatch(/unsaved\.push\(item\.file\?\.name[^\n]*\n\s*continue/)
  })

  it('reports what it did not save', () => {
    // A silent partial success reads as "all N replaced" — the number the button implied.
    expect(code('Upload.jsx')).toMatch(/NOT replaced/)
  })

  it('stops offering version history as a reason not to copy', () => {
    // A revision history is a different promise from a copy, and it was being used to justify
    // not making one.
    expect(code('Upload.jsx')).not.toContain('version history preserves')
  })
})

describe('both SPAs', () => {
  it('carry the same GoogleDrive.jsx', () => {
    // The fix has to land in the shipped SPA too — that is where the exposure was.
    const a = readFileSync(join(HERE, 'GoogleDrive.jsx'), 'utf8')
    const b = readFileSync(join(HERE, '..', '..', 'frontend', 'src', 'GoogleDrive.jsx'), 'utf8')
    expect(a).toBe(b)
  })
})

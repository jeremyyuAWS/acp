// The file-type scope, reported in the Discover sentence.
//
// scanScope.js exists because of an incident where a count was right and unaccompanied: a
// folder-scoped scan reported "1 document" beside a whole-Drive scan reporting 8, and the
// product presented both as the size of the estate. A file-type scope shrinks the estate the
// same way — an operator who scopes to .docx sees fewer rows, and without a sentence cannot tell
// that from a source that lost files.
//
// It is also the audit sentence. "Did you look at everything?" has an honest answer of "no,
// deliberately, and here is how many we did not open".
import { describe, expect, it } from 'vitest'

import { isNarrowScope, scopeSentence } from './scanScope.js'

const drive = (extra) => ({ kind: 'drive', kept: 312, ...extra })

describe('skipped_out_of_scope', () => {
  it('says how many were not read, and why', () => {
    const s = scopeSentence(drive({ skipped_out_of_scope: 47 }), 312)
    expect(s).toContain('47 documents of other file types were not read')
    expect(s).toContain('scoped by file type')
  })

  it('says NOT READ rather than "excluded" or "hidden"', () => {
    // The load-bearing fact is that the content was never opened, rasterised, OCR'd or cached.
    // "Hidden" describes a filter over results and is what the product did BEFORE this — it read
    // every PDF, discarded the findings, and the UI hid the rows.
    const s = scopeSentence(drive({ skipped_out_of_scope: 47 }), 312)
    expect(s).toContain('not read')
    expect(s).not.toContain('hidden')
  })

  it('agrees with itself in the singular', () => {
    const s = scopeSentence(drive({ skipped_out_of_scope: 1 }), 312)
    expect(s).toContain('1 document of other file types was not read')
  })

  it('says nothing when the scope excluded nothing', () => {
    // A .docx scope over an all-Word estate excluded nothing. A sentence there would be noise,
    // and a sentence that appears when nothing happened is how a reader learns to skip it.
    expect(scopeSentence(drive({ skipped_out_of_scope: 0 }), 312)).not.toContain('not read')
    expect(scopeSentence(drive(), 312)).not.toContain('not read')
  })

  it('marks the scan narrow only when something was actually skipped', () => {
    expect(isNarrowScope(drive({ skipped_out_of_scope: 47 }))).toBe(true)
    expect(isNarrowScope(drive({ skipped_out_of_scope: 0 }))).toBe(false)
    expect(isNarrowScope(drive())).toBe(false)
  })

  it('still says nothing at all for a scan with no recorded scope', () => {
    // "No scope recorded" is not evidence of a whole-estate scan, and defaulting to the
    // reassuring reading is how the original defect would come back wearing a label.
    expect(scopeSentence(null, 312)).toBeNull()
    expect(isNarrowScope(null)).toBe(false)
  })
})

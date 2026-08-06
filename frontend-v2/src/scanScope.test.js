// The count never appears without the boundary it counted inside.
//
// Reproduces the 2026-07-30 pair — a one-folder scan reporting 1 and a whole-Drive scan of the
// same account reporting 8, six seconds apart — and asserts the two now read as different
// measurements rather than as an estate that lost seven documents.
import { describe, it, expect } from 'vitest'
import { scopeSentence, scopeLabel, scopeChip, isNarrowScope, isTruncated } from './scanScope.js'

const FOLDER = { kind: 'folder', folder_id: '1W27ULZ', folder_name: 'WCAG Defense Pack',
                 folders_walked: 1, listed: 1, kept: 1, truncated: false }
const DRIVE = { kind: 'drive', raw: 11, scannable: 8, kept: 8, truncated: false }

describe('the incident', () => {
  it('says the folder scan did not look at the rest of the Drive', () => {
    const s = scopeSentence(FOLDER, 1)
    expect(s).toContain('1 document')
    expect(s).toContain('WCAG Defense Pack')
    // The sentence that was missing entirely.
    expect(s).toMatch(/not scanned/)
  })

  it('says the whole-Drive scan covered the whole Drive', () => {
    expect(scopeSentence(DRIVE, 8)).toContain('8 documents across your whole Google Drive')
  })

  it('makes the two scans distinguishable in a list, not just on a detail screen', () => {
    // The scan-history table is where 1 and 8 sat in adjacent rows, both labelled "drive".
    expect(scopeChip(FOLDER).text).not.toBe(scopeChip(DRIVE).text)
    expect(scopeChip(FOLDER).narrow).toBe(true)
    expect(scopeChip(DRIVE).narrow).toBe(false)
  })

  it('flags the folder scan as narrow and the Drive scan as not', () => {
    expect(isNarrowScope(FOLDER)).toBe(true)
    expect(isNarrowScope(DRIVE)).toBe(false)
  })
})

describe('small is not the same claim as incomplete', () => {
  it('does not tell a complete folder scan it could not see everything', () => {
    // A folder scan that covered its folder saw everything it was asked to. Saying otherwise is
    // the mirror-image error: a false alarm on an accurate result.
    expect(isTruncated(FOLDER)).toBe(false)
    expect(scopeSentence(FOLDER, 1)).not.toMatch(/did not see|hit its/)
  })

  it('does say so when a cap genuinely cut the listing short', () => {
    const s = scopeSentence({ kind: 'drive', kept: 500, truncated: true, cap: 2500 }, 500)
    expect(s).toMatch(/did not see/)
    expect(s).toContain('2,500')
  })

  it('warns on a truncated whole-Drive scan even though the kind is wide', () => {
    expect(isNarrowScope({ kind: 'drive', truncated: true })).toBe(true)
    expect(scopeChip({ kind: 'drive', truncated: true }).narrow).toBe(true)
  })
})

describe('an unrecorded scope says nothing', () => {
  // Every scan already in production predates the column. Relabelling those "whole Drive" is how
  // the defect comes back wearing a label the reader has learned to trust.
  it.each([null, undefined, {}, { kind: 'something-new' }])('renders nothing for %o', (scope) => {
    expect(scopeSentence(scope, 8)).toBeNull()
    expect(scopeLabel(scope)).toBeNull()
    expect(isNarrowScope(scope) === true).toBe(false)
  })

  it('never claims a boundary for a scope it cannot name', () => {
    expect(scopeChip({ kind: 'mystery' })).toBeNull()
  })
})

describe('wording', () => {
  it('names the folder when known and stays honest when not', () => {
    expect(scopeLabel(FOLDER)).toContain('WCAG Defense Pack')
    expect(scopeLabel({ kind: 'folder', folder_name: null })).toBe('in one Drive folder')
    // No Drive id leaks into prose — an id is not a name a reader recognises.
    expect(scopeLabel({ kind: 'folder', folder_name: null })).not.toContain('1W27ULZ')
  })

  it('agrees in number', () => {
    expect(scopeSentence(FOLDER, 1)).toContain('1 document ')
    expect(scopeSentence({ ...FOLDER, kept: 2 }, 2)).toContain('2 documents ')
    expect(scopeSentence({ ...FOLDER, kept: 0 }, 0)).toContain('0 documents ')
  })

  it('mentions subfolders only when it actually walked some', () => {
    expect(scopeSentence(FOLDER, 1)).not.toContain('subfolder')
    expect(scopeSentence({ ...FOLDER, folders_walked: 2 }, 3)).toContain('1 subfolder')
    expect(scopeSentence({ ...FOLDER, folders_walked: 4 }, 9)).toContain('3 subfolders')
  })

  it('falls back to the recorded count when the caller passes none', () => {
    expect(scopeSentence(DRIVE, undefined)).toContain('8 documents')
  })

  it('groups thousands so a large estate is readable', () => {
    expect(scopeSentence({ kind: 'drive', kept: 1200, truncated: false }, 1200))
      .toContain('1,200 documents')
  })

  it('labels the non-Drive sources too', () => {
    expect(scopeSentence({ kind: 'local', kept: 3, truncated: false }, 3))
      .toContain('in the local corpus')
    expect(scopeSentence({ kind: 'sharepoint', kept: 4, truncated: false }, 4))
      .toContain('across OneDrive')
  })
})

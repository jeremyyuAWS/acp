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
      .toContain('across your OneDrive')
  })
})

// ── one SharePoint site is a boundary, not an estate ──────────────────────────────────────────
//
// The site picker (#167) made "scan one site" a one-click action, and `kind: 'sharepoint'` had
// meant exactly one thing when it was written: the signed-in user's OneDrive. So a one-site scan
// and a OneDrive scan came back with the same caption and different counts — the incident at the
// top of this file, with Google Drive swapped for Microsoft 365.
describe('a single SharePoint site', () => {
  const SITE = { kind: 'sharepoint', site: 'contoso.sharepoint.com,g1,g2',
                 site_name: 'Policies', kept: 12, truncated: false }
  const ONEDRIVE = { kind: 'sharepoint', site: null, site_name: null, kept: 40, truncated: false }

  it('reads as narrow, exactly as a Drive folder does', () => {
    expect(isNarrowScope(SITE)).toBe(true)
    expect(isNarrowScope(ONEDRIVE)).toBe(false)
  })

  it('names the site rather than claiming the whole of OneDrive', () => {
    expect(scopeLabel(SITE)).toBe('in the SharePoint site “Policies”')
    expect(scopeLabel(ONEDRIVE)).toBe('across your OneDrive')
  })

  it('says what was NOT scanned, at any size', () => {
    // The clause the folder branch has, and for the same reason: the reader's question is "is
    // this my estate?" and one site is not, whether it holds 12 documents or 12,000.
    expect(scopeSentence(SITE, 12)).toMatch(/not scanned/)
    expect(scopeSentence(SITE, 12)).toContain('other SharePoint sites')
    // …and does NOT appear on a OneDrive scan, which really is the whole of that boundary.
    expect(scopeSentence(ONEDRIVE, 40)).not.toMatch(/not scanned/)
  })

  it('promises no scan that does not exist', () => {
    // _sp_list takes one site OR OneDrive; there is no all-sites scan to point a reader at.
    expect(scopeSentence(SITE, 12)).not.toMatch(/whole SharePoint|all sites|every site/i)
  })

  it('never shows the raw Graph site id, which names nothing to a reader', () => {
    // Same guarantee the folder branch makes about a Drive folder id. A compound site id
    // (host,guid,guid) is the least recognisable string in this product.
    const unnamed = { ...SITE, site_name: null }
    expect(scopeLabel(unnamed)).toBe('in one SharePoint site')
    expect(scopeLabel(unnamed)).not.toContain('contoso.sharepoint.com')
    expect(scopeChip(unnamed).text).not.toContain('g1')
  })

  it('is distinguishable from a OneDrive scan in a list, not only on a detail screen', () => {
    // The scan-history table is where two counts sat in adjacent rows under one label.
    expect(scopeChip(SITE).text).not.toBe(scopeChip(ONEDRIVE).text)
    expect(scopeChip(SITE).text).toContain('Policies')
    expect(scopeChip(SITE).narrow).toBe(true)
    expect(scopeChip(ONEDRIVE).narrow).toBe(false)
  })

  it('still says WHICH site when the scan also hit its cap', () => {
    // 'partial listing' alone would lose the site — and a capped site scan is the case where a
    // reader most needs both facts. The truncation still reaches the sentence and the ⚠.
    const capped = { ...SITE, truncated: true }
    expect(scopeChip(capped).text).toContain('Policies')
    expect(isNarrowScope(capped)).toBe(true)
    expect(isTruncated(capped)).toBe(true)
    expect(scopeSentence(capped, 200)).toMatch(/did not see/)
  })
})

// ── SEVERAL SharePoint sites are a boundary too, and a harder one to render ───────────────────
//
// An estate assessment covers a department: thirty team sites in one run. The scope those runs
// record has NO singular `site` — it is a list — and every reader here keyed off the singular
// field. So a thirty-site scan would have rendered exactly as a whole-OneDrive scan does: no ⚠,
// no boundary, a count presented as the estate. That is the 2026-07-30 incident at the top of
// this file, reached from a third direction.
describe('several SharePoint sites', () => {
  const TWO = { kind: 'sharepoint', site: null, site_name: null,
                sites: [{ id: 'c,1,1', name: 'Finance' }, { id: 'c,2,2', name: 'HR' }],
                kept: 512, truncated: false }
  const MANY = { kind: 'sharepoint', site: null, site_name: null,
                 sites: Array.from({ length: 12 }, (_, i) => ({ id: `c,${i},${i}`, name: `Site ${i}` })),
                 kept: 9000, truncated: false }
  const ONEDRIVE = { kind: 'sharepoint', site: null, site_name: null, kept: 40, truncated: false }

  it('reads as narrow — thirty sites out of a tenant is still not the estate', () => {
    expect(isNarrowScope(TWO)).toBe(true)
    expect(isNarrowScope(MANY)).toBe(true)
    expect(isNarrowScope(ONEDRIVE)).toBe(false)
  })

  it('names the sites rather than counting them, while the names fit', () => {
    // The reader's question is WHICH parts of the estate this covers. A bare count answers "how
    // many boundaries" instead — the same substitution of a number for a boundary this module
    // exists to stop, and the reason chosen Drive folders name themselves too.
    expect(scopeLabel(TWO)).toBe('in the SharePoint sites “Finance”, “HR”')
  })

  it('falls back to a count when Graph would not name the sites', () => {
    // A token can read a site's drives while the tenant refuses the site metadata read
    // (scanner._sp_site_name swallows exactly that), so unnamed sites are a real case — and
    // listing only the named half would present a shorter boundary as the whole one.
    const unnamed = { ...TWO, sites: [{ id: 'c,1,1' }, { id: 'c,2,2' }] }
    expect(scopeLabel(unnamed)).toBe('in 2 SharePoint sites')
    expect(scopeLabel(unnamed)).not.toContain('c,1,1')
    const half = { ...TWO, sites: [{ id: 'c,1,1', name: 'Finance' }, { id: 'c,2,2' }] }
    expect(scopeLabel(half)).toBe('in 2 SharePoint sites, including “Finance”')
  })

  it('says what was NOT scanned, at any count', () => {
    expect(scopeSentence(TWO, 512)).toContain('other SharePoint sites')
    expect(scopeSentence(MANY, 9000)).toContain('other SharePoint sites')
    expect(scopeSentence(ONEDRIVE, 40)).not.toMatch(/not scanned/)
  })

  it('says when the site CAP dropped sites the operator selected', () => {
    // `truncated` says the estate is a floor. This says why — sites that were never read, not a
    // file cap that a longer run would clear — which is the difference between waiting and
    // starting a second scan.
    const capped = { ...MANY, truncated: true, sites_omitted: 4 }
    const s = scopeSentence(capped, 9000)
    expect(s).toMatch(/4 further sites you selected were not read/)
    expect(isTruncated(capped)).toBe(true)
  })

  it('does not name an unreadable site inside the boundary it did not cover', () => {
    // SELECTED is not COVERED. A site the token could not read stays on the scope — that is what
    // makes "no site was silently omitted" checkable — but naming it in the boundary claims its
    // documents were counted, which overstates coverage in the one direction that matters.
    const partial = { kind: 'sharepoint', site: null, site_name: null, truncated: true, kept: 40,
                      sites: [{ id: 'a', name: 'Finance', status: 'complete', listed: 40 },
                              { id: 'b', name: 'HR', status: 'blocked', listed: 0 }] }
    // Singular, because ONE site was covered — the boundary is what was read, not what was asked
    // for, and the sentence below carries the rest.
    expect(scopeLabel(partial)).toBe('in the SharePoint site “Finance”')
    const s = scopeSentence(partial, 40)
    expect(s).toMatch(/1 further site you selected was not read \(“HR”\)/)
    expect(s).toMatch(/floor rather than the whole selection/)
    // …and the list row says it too, where a partial run sits beside a complete one.
    expect(scopeChip(partial).text).toBe('🏢 1 of 2 sites')
  })

  it('says 0 of N when every selected site was unreadable', () => {
    // "In 0 sites" is the honest phrase and the one an operator can act on. Naming the sites they
    // asked for would read as a boundary that was measured.
    const none = { kind: 'sharepoint', site: null, kept: 0, truncated: true,
                   sites: [{ id: 'a', name: 'Finance', status: 'blocked' },
                           { id: 'b', name: 'HR', status: 'blocked' }] }
    expect(scopeLabel(none)).toBe('in 0 of 2 selected SharePoint sites')
  })

  it('treats a scan recorded before per-site statuses as fully covered', () => {
    // Every such run had exactly one site and either completed or failed outright. Reading a
    // missing status as "unread" would relabel every historical SharePoint scan a partial one.
    const legacy = { kind: 'sharepoint', site: 'c,1,1', site_name: 'Policies', kept: 12 }
    expect(scopeLabel(legacy)).toBe('in the SharePoint site “Policies”')
    expect(scopeSentence(legacy, 12)).not.toMatch(/not read/)
  })

  it('is distinguishable from one site and from OneDrive in a list', () => {
    expect(scopeChip(TWO).text).toBe('🏢 2 sites')
    expect(scopeChip(TWO).narrow).toBe(true)
    expect(scopeChip(TWO).text).not.toBe(scopeChip(ONEDRIVE).text)
  })

  it('reads a one-site list exactly as the singular fields did', () => {
    // The backend writes `sites` even for a one-site run so consumers read one field. That must
    // not change what a single-site scan looks like — the singular spelling is what every scan
    // recorded before multi-site carries.
    const asList = { kind: 'sharepoint', site: null, site_name: null,
                     sites: [{ id: 'c,1,1', name: 'Policies' }], kept: 12, truncated: false }
    const asSingular = { kind: 'sharepoint', site: 'c,1,1', site_name: 'Policies',
                         kept: 12, truncated: false }
    expect(scopeLabel(asList)).toBe(scopeLabel(asSingular))
    expect(scopeChip(asList).text).toBe(scopeChip(asSingular).text)
    expect(scopeSentence(asList, 12)).toBe(scopeSentence(asSingular, 12))
  })
})

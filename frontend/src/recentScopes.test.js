/**
 * Reusable scopes, derived from the runs that actually happened.
 *
 * The shortcut is "run what I ran last time" — and the whole risk of a shortcut is that it is
 * clicked without being read. So every case here is about what the list must REFUSE to offer, or
 * must say out loud, rather than about the happy path:
 *
 *   · a run with NO recorded scope must not appear. NULL means unknown (a scan predating the
 *     column, or scope JSON that would not decode). Applied, it becomes an empty selection, and
 *     an empty selection means EVERYTHING — silent widening, reached by clicking a control
 *     labelled as a narrowing. The one direction nobody re-checks.
 *   · a Drive scope must not be offered for a OneDrive scan. Graph ids are `<driveId>/<itemId>`
 *     and Drive ids are not; the ids would be accepted, resolve to nothing, and the run would
 *     come back empty with a boundary that looks deliberate.
 *   · "entire source, everything supported" must not appear. It is the wizard's own default, so
 *     it is a control that does nothing — and a list with no-ops in it stops being read.
 *   · the same boundary run five times must appear once, and folder ORDER must not make two
 *     entries out of one estate.
 *   · a carve-out must never be dropped on reuse, and must never be printed as a raw id. A run
 *     records exclusion ids WITHOUT names, so the label says how many and admits the names are
 *     not recorded — the alternative is an opaque Drive id where a folder name belongs, which is
 *     not a boundary a reader can check anything against.
 *   · the label must carry BOTH halves, locations and criteria. A reader given one without the
 *     other cannot reconstruct what was measured — which is exactly why the run records them
 *     together (scanner.py: "the two belong together").
 */
import { describe, it, expect } from 'vitest'
import {
  scopeFamily, scopeKey, isDefaultScope, reusableScopes, describeScope, whenLabel,
} from './recentScopes.js'

const run = (id, at, source, scope) => ({ id, completed_at: at, source, scope })
const HR = { id: 'hr', name: 'HR' }
const FIN = { id: 'fin', name: 'Finance' }

describe('scopeFamily mirrors how a scan resolves its source', () => {
  it('folds all + drive into drive, and onedrive into sharepoint', () => {
    expect(scopeFamily('all')).toBe('drive')
    expect(scopeFamily('drive')).toBe('drive')
    expect(scopeFamily('onedrive')).toBe('sharepoint')
    expect(scopeFamily('sharepoint')).toBe('sharepoint')
  })

  it('is null for a source with no folder ids of its own', () => {
    expect(scopeFamily('local')).toBe(null)
    expect(scopeFamily(undefined)).toBe(null)
  })
})

describe('what the list refuses to offer', () => {
  it('skips a run with no recorded scope', () => {
    // THE load-bearing case. "No scope recorded" is not evidence of a whole-Drive scan, and
    // offering it would apply as one.
    const scans = [run('a', '2026-08-18T10:00:00Z', 'drive', null),
                   run('b', '2026-08-17T10:00:00Z', 'drive', { folders: [HR] })]
    expect(reusableScopes(scans, 'drive').map((e) => e.scanId)).toEqual(['b'])
  })

  it('skips a scope from the other source family', () => {
    const scans = [run('sp', '2026-08-18T10:00:00Z', 'sharepoint', { folders: [{ id: 'd1/i1', name: 'Team' }] }),
                   run('gd', '2026-08-17T10:00:00Z', 'drive', { folders: [HR] })]
    expect(reusableScopes(scans, 'drive').map((e) => e.scanId)).toEqual(['gd'])
    expect(reusableScopes(scans, 'sharepoint').map((e) => e.scanId)).toEqual(['sp'])
  })

  it('skips the wizard default — entire source, everything supported', () => {
    const scans = [run('a', '2026-08-18T10:00:00Z', 'drive', { kind: 'drive', folders: [], scan_scope: null })]
    expect(isDefaultScope(scans[0].scope)).toBe(true)
    expect(reusableScopes(scans, 'drive')).toEqual([])
  })

  it('keeps an entire-source scope that DID restrict the criteria', () => {
    // Not the default: same locations, different question asked of them.
    const scope = { kind: 'drive', folders: [], scan_scope: { '1.1.1': ['pdf'] } }
    expect(isDefaultScope(scope)).toBe(false)
    expect(reusableScopes([run('a', '2026-08-18T10:00:00Z', 'drive', scope)], 'drive').length).toBe(1)
  })
})

describe('one entry per distinct boundary', () => {
  it('dedupes repeats and keeps the newest', () => {
    const scope = { folders: [HR] }
    const scans = [run('new', '2026-08-18T10:00:00Z', 'drive', scope),
                   run('old', '2026-08-01T10:00:00Z', 'drive', { folders: [HR] })]
    const out = reusableScopes(scans, 'drive')
    expect(out.length).toBe(1)
    expect(out[0].scanId).toBe('new')
  })

  it('treats folder ORDER as the same estate', () => {
    // "HR then Finance" and "Finance then HR" cover the same files. Two entries would fill the
    // list with the same scope and push the genuinely different one off the end.
    expect(scopeKey({ folders: [HR, FIN] })).toBe(scopeKey({ folders: [FIN, HR] }))
  })

  it('treats a different criteria set as a different scope', () => {
    expect(scopeKey({ folders: [HR], scan_scope: { '1.1.1': ['pdf'] } }))
      .not.toBe(scopeKey({ folders: [HR], scan_scope: { '1.4.3': ['pdf'] } }))
  })

  it('sorts by completion rather than trusting the caller order, and honours the limit', () => {
    const scans = [run('c', '2026-08-01T10:00:00Z', 'drive', { folders: [{ id: 'c', name: 'C' }] }),
                   run('a', '2026-08-18T10:00:00Z', 'drive', { folders: [HR] }),
                   run('b', '2026-08-10T10:00:00Z', 'drive', { folders: [FIN] })]
    expect(reusableScopes(scans, 'drive').map((e) => e.scanId)).toEqual(['a', 'b', 'c'])
    expect(reusableScopes(scans, 'drive', 2).map((e) => e.scanId)).toEqual(['a', 'b'])
  })
})

describe('carve-outs survive the round trip', () => {
  it('carries the exclusion ids through, and flags that they are unnamed', () => {
    // A run records `excluded` as bare ids. Dropping them on reuse would WIDEN the scan while the
    // label still read as a narrowing; printing them raw would put a Drive id where a folder name
    // belongs. So: carried, and marked.
    const out = reusableScopes([run('a', '2026-08-18T10:00:00Z', 'drive',
      { folders: [HR], excluded: ['arch'] })], 'drive')
    expect(out[0].excluded).toEqual([{ id: 'arch', name: null }])
    expect(out[0].unnamedExclusions).toBe(true)
  })

  it('an excluded folder makes it a different scope from the same folder without one', () => {
    expect(scopeKey({ folders: [HR], excluded: ['arch'] })).not.toBe(scopeKey({ folders: [HR] }))
  })

  it('accepts the {id,name} shape too, and then does not flag it', () => {
    const out = reusableScopes([run('a', '2026-08-18T10:00:00Z', 'drive',
      { folders: [HR], excluded: [{ id: 'arch', name: 'Archive' }] })], 'drive')
    expect(out[0].unnamedExclusions).toBe(false)
  })
})

describe('the label names the whole boundary', () => {
  const entry = (scope) => reusableScopes([run('a', '2026-08-18T10:00:00Z', 'drive', scope)], 'drive')[0]

  it('says where AND what', () => {
    const t = describeScope(entry({ folders: [HR, FIN], scan_scope: { '1.1.1': ['pdf'] } }))
    expect(t).toMatch(/HR, Finance/)
    expect(t).toMatch(/1 criteria/)
  })

  it('says "Everything supported" rather than leaving the criteria half blank', () => {
    // A blank half reads as "no criteria", which is the opposite of what an unrestricted scope
    // means — the same inversion the empty folder selection has.
    expect(describeScope(entry({ folders: [HR] }))).toMatch(/Everything supported/)
  })

  it('names the carve-out when the run recorded names', () => {
    expect(describeScope(entry({ folders: [HR], excluded: [{ id: 'arch', name: 'Archive' }] })))
      .toMatch(/except Archive/)
  })

  it('admits when it cannot name the carve-out, rather than printing an id', () => {
    const t = describeScope(entry({ folders: [HR], excluded: ['arch'] }))
    expect(t).toMatch(/except 1 folder \(not named on that run\)/)
    expect(t, 'a raw Drive id leaked into the label').not.toMatch(/arch/)
  })
})

describe('whenLabel', () => {
  const now = new Date('2026-08-19T12:00:00Z')
  it('reads as relative near the present and as a date beyond it', () => {
    expect(whenLabel('2026-08-19T09:00:00Z', now)).toBe('today')
    expect(whenLabel('2026-08-18T09:00:00Z', now)).toBe('yesterday')
    expect(whenLabel('2026-08-01T09:00:00Z', now)).toMatch(/Aug/)
  })

  it('says nothing rather than "Invalid Date" when the stamp is missing or junk', () => {
    expect(whenLabel(null, now)).toBe('')
    expect(whenLabel('not-a-date', now)).toBe('')
  })
})

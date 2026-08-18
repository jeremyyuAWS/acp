/**
 * sourceOps — the derivation behind the "Manage <source>" panel.
 *
 * The defect this module exists to stop was not a layout problem. The drawer's subtitle read
 * `undefined · 0 docs · agent: undefined` beside a card badged **Healthy**, and both halves were
 * produced the same way: a missing field stringified into a template literal, and a file filter
 * that matched a card id (`sp-root`) against a file row's source key (`sharepoint`). Neither
 * failed loudly. The first four tests below are that incident, pinned.
 *
 * The rest pin the two rules the module is built on: every number traces to a prop, and a value
 * ACP does not have comes back as `null` (rendered as a stated absence) rather than as `0`.
 */
import { describe, it, expect } from 'vitest'
import {
  sourceKeys, filesForSource, runsForSource, inventoryFacts, dispositionOf, dispositionRows,
  runOutcome, runDurationMs, needsAttention, scopeFacts,
  fmtSize, fmtDuration, fmtWhen, fmtCount, orAbsent, NOT_AVAILABLE, NOT_CONFIGURED,
} from './sourceOps.js'

const ONEDRIVE = { id: 'sp-root', type: 'onedrive', name: 'OneDrive' }
const F = (over = {}) => ({ file: 'a.docx', type: 'docx', source: 'sharepoint', owner: 'Rae', department: 'HR', sizeKB: 100, tags: [], ...over })

describe('resolving which rows belong to a card', () => {
  it('matches OneDrive file rows that are keyed `sharepoint`, not by the card id', () => {
    // The live bug: the card is `sp-root`, Graph's rows say `sharepoint`, and the old filter was
    // `f.source === selSrc.id`. It matched nothing and the drawer reported "0 docs".
    const files = [F(), F({ file: 'b.pdf', source: 'sharepoint' }), F({ file: 'c.docx', source: 'gdrive' })]
    expect(filesForSource(files, ONEDRIVE).map((f) => f.file)).toEqual(['a.docx', 'b.pdf'])
  })

  it('does not hand a source somebody else’s rows', () => {
    const files = [F({ source: 'gdrive' })]
    expect(filesForSource(files, ONEDRIVE)).toEqual([])
  })

  it('resolves Drive under every key the app uses for it', () => {
    expect(sourceKeys({ id: '_gdrive', type: 'google_drive' })).toEqual(expect.arrayContaining(['gdrive', 'drive', 'google_drive']))
  })

  it('never treats an all-sources run as this source’s run', () => {
    // `source: 'all'` is a real value the scan API returns. Counting it here would attribute
    // another connector's failures to this card.
    const runs = runsForSource([{ id: 'r', source: 'all', completed_at: '2026-08-18T10:00:00Z' }], ONEDRIVE)
    expect(runs).toEqual([])
  })

  it('orders this source’s runs newest first', () => {
    const scans = [
      { id: 'old', source: 'sharepoint', completed_at: '2026-08-16T10:00:00Z' },
      { id: 'new', source: 'sharepoint', completed_at: '2026-08-18T10:00:00Z' },
    ]
    expect(runsForSource(scans, ONEDRIVE).map((r) => r.id)).toEqual(['new', 'old'])
  })
})

describe('inventory facts distinguish “none” from “we do not know”', () => {
  it('counts what the rows support', () => {
    const inv = inventoryFacts([F(), F({ owner: 'Sam', department: 'Legal', sizeKB: 924 })])
    expect(inv).toMatchObject({ documents: 2, bytesKb: 1024, owners: 2, departments: 2 })
  })

  it('reports folders as null — not 0 — when the source names files flatly', () => {
    // SIM and several connectors return bare filenames. "0 folders" reads as a scope problem;
    // "Not available" is the fact.
    expect(inventoryFacts([F()]).folders).toBeNull()
  })

  it('counts folders when the rows carry paths', () => {
    expect(inventoryFacts([F({ file: 'HR/policies/leave.docx' })]).folders).toBe(1)
  })

  it('withholds a total size rather than understating it from partial data', () => {
    // One sized row out of two would render a total smaller than the estate, with nothing
    // on screen saying so.
    expect(inventoryFacts([F(), F({ sizeKB: undefined })]).bytesKb).toBeNull()
  })
})

describe('the discovery outcome table is a partition', () => {
  const label = (f) => f.retention || 'Keep'

  it('puts every file in exactly one bucket, summing to the total', () => {
    const files = [
      F(), F({ type: 'mp4' }), F({ retention: 'Archive candidate' }),
      F({ retention: 'Delete candidate' }), F({ locked: true }), F({ excluded: true }),
    ]
    const rows = dispositionRows(files, label)
    expect(rows.reduce((a, r) => a + r.count, 0)).toBe(files.length)
    expect(Object.fromEntries(rows.map((r) => [r.key, r.count])))
      .toEqual({ assessable: 1, unsupported: 1, archive: 1, delete: 1, excluded: 1, unreadable: 1 })
  })

  it('does not count an archive candidate as available for assessment', () => {
    // Assess excludes lifecycle-flagged rows by default (#320). Counting a DOCX archive
    // candidate as assessable would advertise coverage over a file Assess will skip.
    expect(dispositionOf(F({ retention: 'Archive candidate' }), label)).toBe('archive')
  })

  it('reports an unreadable file as unreadable whatever its format', () => {
    expect(dispositionOf(F({ locked: true }), label)).toBe('unreadable')
  })

  it('colours archive and deletion candidates as review, not failure', () => {
    const tone = Object.fromEntries(dispositionRows([], label).map((r) => [r.key, r.tone]))
    expect(tone.archive).toBe('review')
    expect(tone.delete).toBe('review')
    expect(tone.unreadable).toBe('fail')
  })
})

describe('run outcome separates “completed” from “completed cleanly”', () => {
  it('calls a run that could not read some files completed WITH WARNINGS', () => {
    expect(runOutcome({ completed_at: '2026-08-18T10:00:00Z', error: 18 }).label).toMatch(/warnings/i)
  })

  it('calls a clean run completed', () => {
    expect(runOutcome({ completed_at: '2026-08-18T10:00:00Z', error: 0 }).key).toBe('ok')
  })

  it('does not claim a still-running scan finished', () => {
    expect(runOutcome({ status: 'running', started_at: '2026-08-18T10:00:00Z' }).key).toBe('running')
  })

  it('measures duration from the run’s own timestamps, or not at all', () => {
    expect(runDurationMs({ started_at: '2026-08-18T10:00:00Z', completed_at: '2026-08-18T10:08:42Z' })).toBe(522000)
    expect(runDurationMs({ completed_at: '2026-08-18T10:08:42Z' })).toBeNull()
  })
})

describe('needs attention lists only what is actionable', () => {
  const label = (f) => f.retention || 'Keep'

  it('is empty for a clean, inventoried source', () => {
    expect(needsAttention({ files: [F()], runs: [{ id: 'r', completed_at: '2026-08-18T10:00:00Z', error: 0 }], labelOf: label }))
      .toEqual([])
  })

  it('raises unreadable files in red and deletion candidates in amber', () => {
    const items = needsAttention({
      files: [F({ locked: true }), F({ retention: 'Delete candidate' })],
      runs: [{ id: 'r', completed_at: '2026-08-18T10:00:00Z', error: 1 }], labelOf: label,
    })
    expect(items.find((i) => i.key === 'inaccessible').tone).toBe('fail')
    const del = items.find((i) => i.key === 'delete')
    expect(del.tone).toBe('review')
    expect(del.detail).toMatch(/approval is required/i)
  })

  it('says a source has never been inventoried instead of showing it as empty', () => {
    const items = needsAttention({ files: [], runs: [], labelOf: label })
    expect(items.map((i) => i.key)).toContain('never')
  })
})

describe('nothing renders as undefined', () => {
  it('turns the exact string that caused the incident into a stated absence', () => {
    // `${source.agent}` on a missing field produces the literal "undefined". Guarding on
    // nullish alone would let it through — it is already a string by then.
    expect(orAbsent(undefined)).toBe(NOT_AVAILABLE)
    expect(orAbsent('undefined')).toBe(NOT_AVAILABLE)
    expect(orAbsent('')).toBe(NOT_AVAILABLE)
    expect(orAbsent(null, NOT_CONFIGURED)).toBe(NOT_CONFIGURED)
    expect(orAbsent('OneDrive')).toBe('OneDrive')
  })

  it('keeps every scope field present, with a null value the caller can label', () => {
    // A dropped row and a not-configured row look identical once the row is gone.
    const facts = scopeFacts({})
    expect(facts.map((f) => f.label)).toEqual(['Account', 'Root', 'Access', 'Write-back', 'Monitoring'])
    expect(facts.find((f) => f.label === 'Monitoring').value).toBeNull()
    expect(facts.find((f) => f.label === 'Write-back').value).toBe('Not enabled')
  })

  it('reads a schedule off the source when it has one', () => {
    expect(scopeFacts({ agent: 'daily' }).find((f) => f.label === 'Monitoring').value).toBe('Every 24 hours')
  })

  it('formats sizes, durations, times and counts, and says so when it cannot', () => {
    expect(fmtSize(512)).toBe('512 KB')
    expect(fmtSize(2048)).toBe('2.0 MB')
    expect(fmtSize(null)).toBe(NOT_AVAILABLE)
    expect(fmtDuration(522000)).toBe('8m 42s')
    expect(fmtDuration(null)).toBe(NOT_AVAILABLE)
    expect(fmtWhen('not-a-date')).toBe(NOT_AVAILABLE)
    expect(fmtCount(null)).toBe(NOT_AVAILABLE)
    expect(fmtCount(12486)).toBe('12,486')
  })
})

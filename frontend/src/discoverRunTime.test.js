import { describe, it, expect } from 'vitest'
import {
  NOT_RECORDED_NOTE, STALE_AFTER_MS, TIME_SOURCES, formatInventoryTime, inventorySnapshot,
  newestRowStamp, parseAt, resolveInventoryTime,
} from './discoverRunTime.js'

const AT = '2026-08-19T10:00:00Z'
// parseAt canonicalises to a UTC ISO instant (see its docstring); this is the same moment.
const AT_ISO = '2026-08-19T10:00:00.000Z'
const NOW = Date.parse('2026-08-19T12:30:00Z')

describe('discoverRunTime — where the instant comes from', () => {
  it('prefers the run-level discovery stamp', () => {
    const hit = resolveInventoryTime({
      run: { discovered_at: AT, completed_at: '2026-08-20T00:00:00Z' },
      rows: [{ discovered_at: '2026-08-19T09:00:00Z' }],
    })
    expect(hit.at).toBe(AT_ISO)
    expect(hit.source).toBe(TIME_SOURCES.RUN)
  })

  it('accepts the stamp from the inventory envelope too', () => {
    const hit = resolveInventoryTime({ inventory: { discovered_at: AT, rows: [] } })
    expect(hit.source).toBe(TIME_SOURCES.RUN)
  })

  it('derives it from the newest per-file stamp when the run has none', () => {
    // scan_inventory.discovered_at is real persisted data — add_inventory writes it per file and
    // a re-list does not overwrite it — so its maximum is when the inventory was last added to.
    const hit = resolveInventoryTime({
      run: { id: 's1', started_at: '2026-08-19T09:00:00Z' },
      rows: [
        { discovered_at: '2026-08-19T09:58:00Z' },
        { discovered_at: AT },
        { discovered_at: '2026-08-19T09:59:00Z' },
      ],
    })
    expect(hit.at).toBe(AT_ISO)
    expect(hit.source).toBe(TIME_SOURCES.ROWS)
  })

  it('falls back to the scan completion last, and labels it as an upper bound', () => {
    const hit = resolveInventoryTime({ run: { completed_at: AT }, rows: [] })
    expect(hit.source).toBe(TIME_SOURCES.COMPLETED)
    expect(hit.label).toMatch(/upper bound/i)
  })

  it('NEVER uses started_at — the listing beginning is not the listing finishing', () => {
    expect(resolveInventoryTime({ run: { started_at: AT, status: 'discovered' }, rows: [] })).toBeNull()
  })

  it('returns null when nothing was persisted, rather than a time', () => {
    expect(resolveInventoryTime({})).toBeNull()
    expect(resolveInventoryTime({ run: {}, inventory: { rows: [] }, rows: [] })).toBeNull()
  })

  it('rejects an unparseable stamp instead of rendering Invalid Date', () => {
    expect(parseAt('not a date')).toBeNull()
    expect(parseAt('')).toBeNull()
    expect(parseAt(null)).toBeNull()
    expect(resolveInventoryTime({ run: { discovered_at: 'soon' }, rows: [] })).toBeNull()
  })

  it('ignores rows with no stamp when picking the newest', () => {
    expect(newestRowStamp([{ discovered_at: null }, { discovered_at: AT }, {}])).toBe(AT_ISO)
    expect(newestRowStamp([{ discovered_at: null }, {}])).toBeNull()
    expect(newestRowStamp(null)).toBeNull()
  })

  it('compares instants, not strings, across offsets', () => {
    // Same moment, two spellings. A lexical max would pick the wrong one.
    const hit = resolveInventoryTime({
      rows: [{ discovered_at: '2026-08-19T10:00:00Z' }, { discovered_at: '2026-08-19T04:00:00-07:00' }],
    })
    expect(Date.parse(hit.at)).toBe(Date.parse('2026-08-19T11:00:00Z'))
  })
})

describe('discoverRunTime — how it reads', () => {
  it('names the time zone, because the reader may not be in the scanner’s', () => {
    const f = formatInventoryTime(AT, { now: NOW })
    expect(f.absolute).toMatch(/2026/)
    expect(f.absolute).toMatch(/UTC|GMT|[A-Z]{2,5}T?$|\+/)
  })

  it('reports the age relative to an injected clock', () => {
    expect(formatInventoryTime(AT, { now: NOW }).relative).toBe('3 hours ago')
    expect(formatInventoryTime(AT, { now: Date.parse('2026-08-19T10:00:30Z') }).relative).toBe('just now')
    expect(formatInventoryTime(AT, { now: Date.parse('2026-08-26T10:00:00Z') }).relative).toBe('7 days ago')
  })

  it('says so when the record is ahead of the browser rather than hiding the skew', () => {
    expect(formatInventoryTime(AT, { now: Date.parse('2026-08-19T09:00:00Z') }).relative)
      .toBe('in 1 hour')
  })

  it('flags a snapshot older than the staleness window', () => {
    expect(formatInventoryTime(AT, { now: NOW }).stale).toBe(false)
    expect(formatInventoryTime(AT, { now: NOW + STALE_AFTER_MS }).stale).toBe(true)
  })

  it('returns null for an unusable instant instead of a formatted lie', () => {
    expect(formatInventoryTime(null, { now: NOW })).toBeNull()
    expect(formatInventoryTime('nope', { now: NOW })).toBeNull()
  })
})

describe('discoverRunTime — the absence is an answer', () => {
  it('reports recorded:false with a note, and no time at all', () => {
    const s = inventorySnapshot({ run: { started_at: AT }, rows: [], now: NOW })
    expect(s.recorded).toBe(false)
    expect(s.at).toBeNull()
    expect(s.absolute).toBeUndefined()
    expect(s.note).toBe(NOT_RECORDED_NOTE)
  })

  it('assembles the whole line when it is recorded', () => {
    const s = inventorySnapshot({ run: { discovered_at: AT }, now: NOW })
    expect(s).toMatchObject({ recorded: true, at: AT_ISO, source: TIME_SOURCES.RUN, relative: '3 hours ago', stale: false })
    expect(s.note).toBeNull()
  })

  it('reads rows off the inventory envelope when none are passed directly', () => {
    const s = inventorySnapshot({ inventory: { rows: [{ discovered_at: AT }] }, now: NOW })
    expect(s.at).toBe(AT_ISO)
    expect(s.source).toBe(TIME_SOURCES.ROWS)
  })
})

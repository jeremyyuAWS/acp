/**
 * R20 · the CSV companion to the remediation PDF. Same model, machine-readable rows.
 *
 * Pins: one row per (document × criterion); RFC-4180 quoting of before/after values that contain
 * commas, quotes and newlines; the "time not recorded" honesty carried from the PDF; a capped list
 * flagged with a leading # PARTIAL line; and end-to-end that buildRemediationCsv shares
 * buildRemediationModel with the PDF (so the two exports can't diverge).
 */
import { describe, it, expect } from 'vitest'
import { remediationCsvRows, remediationCsvText, buildRemediationCsv, CSV_COLUMNS } from './remediationCsv.js'

const MODEL = {
  org: 'UTSW', level: 'AA', partial: null,
  documents: [
    { name: 'Q3 Board Pack.pdf', dir: 'Finance/2024', fmt: 'pdf', remediatedAt: '20 Aug 2026, 16:57', awaiting: 5,
      items: [
        { sc: '1.3.1', name: 'Info and Relationships', category: 'Structure',
          before: '<TD>Region</TD>', after: '<TH scope="col">Region</TH>', note: null, at: '20 Aug, 16:57' },
        { sc: '1.1.1', name: 'Non-text Content', category: 'Text alternatives',
          before: '(no alt text)', after: 'Bar chart: revenue rising from £4.1m to £5.8m, "Q3" highest', note: 'chart', at: null },
      ] },
    { name: 'Headcount Model.xlsx', dir: '', fmt: 'xlsx', remediatedAt: null, awaiting: 0,
      items: [ { sc: '3.1.1', name: 'Language of Page', category: 'Understandable',
                 before: 'unset', after: 'en-GB', note: null, at: '20 Aug, 16:58' } ] },
  ],
}

describe('remediationCsvRows', () => {
  it('emits one row per document × criterion, with the model values', () => {
    const rows = remediationCsvRows(MODEL)
    expect(rows).toHaveLength(3)
    expect(rows[0]).toMatchObject({ Document: 'Q3 Board Pack.pdf', Folder: 'Finance/2024', Format: '.pdf',
      'Success criterion': '1.3.1', 'Awaiting review (document)': 5 })
  })
  it('shows "(root)" for a document with no folder', () => {
    expect(remediationCsvRows(MODEL).find((r) => r.Document === 'Headcount Model.xlsx').Folder).toBe('(root)')
  })
  it('reads "time not recorded" for an unstamped change, never a substitute', () => {
    const altRow = remediationCsvRows(MODEL).find((r) => r['Success criterion'] === '1.1.1')
    expect(altRow['Applied at']).toBe('time not recorded')      // the model's at was null
  })
})

describe('remediationCsvText', () => {
  it('starts with the exact header row', () => {
    expect(remediationCsvText(MODEL).split('\r\n')[0]).toBe(CSV_COLUMNS.join(','))
  })
  it('RFC-4180 quotes values with commas / quotes and doubles embedded quotes', () => {
    const line = remediationCsvText(MODEL).split('\r\n').find((l) => l.includes('Bar chart'))
    // the After value has a comma AND embedded quotes → must be wrapped and quotes doubled
    expect(line).toContain('"Bar chart: revenue rising from £4.1m to £5.8m, ""Q3"" highest"')
  })
  it('emits CRLF line endings and a trailing newline', () => {
    const txt = remediationCsvText(MODEL)
    expect(txt.endsWith('\r\n')).toBe(true)
    expect(txt.split('\r\n').filter(Boolean)).toHaveLength(1 + 3)   // header + 3 rows
  })
  it('flags a capped/partial list with a leading # PARTIAL comment', () => {
    const txt = remediationCsvText({ ...MODEL, partial: 500 })
    expect(txt.split('\r\n')[0]).toMatch(/^# PARTIAL: server returned the maximum of 500/)
  })
})

describe('buildRemediationCsv — shares the PDF model', () => {
  it('turns raw scan inputs into rows via buildRemediationModel, and names the file from the org', () => {
    const out = buildRemediationCsv({
      files: [{ file: 'Finance/Q3 Board Pack.pdf', remediated_at: '2026-08-20T16:57:00Z' }],
      diffsByFile: { 'Finance/Q3 Board Pack.pdf': [
        { rule_id: '1.3.1', before: '<TD>', after: '<TH>' },
      ] },
      appliedFixes: [{ file: 'Finance/Q3 Board Pack.pdf', rule_id: '1.3.1', created_at: '2026-08-20T16:57:00Z' }],
      org: 'UTSW Pilot', level: 'AA',
    })
    expect(out.filename).toBe('utsw-pilot-changes.csv')
    expect(out.model.totals.documents).toBe(1)
    const rows = remediationCsvRows(out.model)
    expect(rows).toHaveLength(1)
    expect(rows[0]['Success criterion']).toBe('1.3.1')
    expect(rows[0]['Applied at']).not.toBe('time not recorded')   // this one WAS stamped
  })
  it('produces a header-only CSV (no rows) when nothing was remediated', () => {
    const out = buildRemediationCsv({ files: [], diffsByFile: {}, appliedFixes: [] })
    expect(remediationCsvRows(out.model)).toHaveLength(0)
    expect(out.text.trim()).toBe(CSV_COLUMNS.join(','))
  })
})

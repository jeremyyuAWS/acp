import { describe, it, expect } from 'vitest'
import {
  COLUMNS, FORBIDDEN, MISSING, csvValue, exportFilename, isBlank, isMissing,
  normalizeRows, selectColumns, toCsv, toJson,
} from './inventoryExport.js'

// A row exactly as GET /scans/{id}/inventory returns it (store._INV_COLS + the capability the
// route derives). Rebuilt here rather than imported so a change to the route's shape shows up as
// a failing test with a name, instead of silently reshaping the fixture too.
const ROW = {
  scan_id: 'scan-1', file: 'HR Policy.docx', drive_file_id: 'gd-1', drive_id: null,
  mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  size_kb: 412, doc_class: 'document', checksum: 'md5-aaa', path: '/HR/HR Policy.docx',
  created_at: '2024-02-01T09:00:00Z', source_modified: '2025-06-11T14:22:00Z',
  owner: 'dana@example.com', parent_folder: '/HR', discovered_at: '2026-08-19T10:00:00Z',
  lifecycle_status: 'Active', lifecycle_rule_id: null, lifecycle_reason: null,
  exclusion_reason: null, format: 'docx', status: 'assessable',
}
const ROW2 = {
  ...ROW, file: 'old-brochure.pdf', path: '/Marketing/old-brochure.pdf', parent_folder: '/Marketing',
  format: 'pdf', mime: 'application/pdf', doc_class: 'document', size_kb: 0,
  owner: null, checksum: null, discovered_at: '2026-08-19T10:04:00Z',
  lifecycle_status: 'Archive Candidate', lifecycle_rule_id: 'legacy-5y',
  lifecycle_reason: 'not modified in 6.1 yrs',
}

const header = (csv) => csv.split('\r\n')[0].split(',')
const dataRows = (csv) => csv.split('\r\n').slice(1).filter(Boolean)
const cells = (line) => {
  // Minimal RFC-4180 reader, so the tests read the file the way a consumer would rather than
  // asserting against the string we just built.
  const out = []
  let cur = '', q = false
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    if (q) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i++ }
      else if (c === '"') q = false
      else cur += c
    } else if (c === '"') q = true
    else if (c === ',') { out.push(cur); cur = '' }
    else cur += c
  }
  out.push(cur)
  return out
}

describe('inventoryExport — what the file may contain (ADR 0020)', () => {
  it('ships only metadata columns, never an assessed one', () => {
    const keys = new Set(COLUMNS.map((c) => c.key))
    FORBIDDEN.forEach((f) => expect(keys.has(f)).toBe(false))
  })

  it('drops assessed fields even when the caller hands them in on the row', () => {
    // The shape a caller produces by merging file_records into inventory rows. The allow-list is
    // what stops that mistake reaching a customer, so drive it rather than trusting it.
    const poisoned = { ...ROW, score: 62, compliant: 0, issues: [{ wcag: 'SC_1_1_1' }],
      findings: 3, engine: 'office', pages: 12, remediated_at: '2026-08-20T00:00:00Z' }
    const { csv } = toCsv([poisoned])
    FORBIDDEN.forEach((f) => expect(header(csv)).not.toContain(f))
    expect(csv).not.toContain('62')
    expect(csv).not.toMatch(/SC_1_1_1/)
    const doc = toJson([poisoned])
    expect(JSON.stringify(doc)).not.toMatch(/SC_1_1_1/)
  })

  it('labels the assessability column as a projection, not a verdict', () => {
    const { csv } = toCsv([ROW])
    expect(header(csv)).toContain('assessability_projected')
    expect(header(csv)).not.toContain('status')
  })
})

describe('inventoryExport — missing is not zero and not blank', () => {
  it('writes the missing token for an absent value', () => {
    expect(csvValue(null)).toBe(MISSING)
    expect(csvValue(undefined)).toBe(MISSING)
  })

  it('writes 0 as 0 — a 0 KB file is a fact, not an absence', () => {
    expect(csvValue(0)).toBe('0')
    expect(isMissing(0)).toBe(false)
  })

  it('writes a collected-but-empty string as an empty field, distinct from missing', () => {
    expect(csvValue('')).toBe('')
    expect(isBlank('')).toBe(true)
    expect(isMissing('')).toBe(false)
  })

  it('keeps the three cases apart in one file', () => {
    const rows = [
      { ...ROW, file: 'a.docx', owner: 'dana@example.com', size_kb: 10 },
      { ...ROW, file: 'b.docx', owner: '', size_kb: 0 },            // collected, empty / genuinely 0
      { ...ROW, file: 'c.docx', owner: null, size_kb: null },        // never collected
    ]
    const { csv } = toCsv(rows)
    const h = header(csv)
    const owner = h.indexOf('owner')
    const size = h.indexOf('size_kb')
    const [a, b, c] = dataRows(csv).map(cells)
    expect([a[owner], b[owner], c[owner]]).toEqual(['dana@example.com', '', MISSING])
    expect([a[size], b[size], c[size]]).toEqual(['10', '0', MISSING])
  })

  it('treats a non-finite number as missing rather than printing NaN', () => {
    expect(csvValue(NaN)).toBe(MISSING)
    expect(csvValue(Infinity)).toBe(MISSING)
  })

  it('uses null, not a token, in JSON', () => {
    const doc = toJson([{ ...ROW, owner: null }])
    expect(doc.rows[0].owner).toBeUndefined()   // dropped: the only row has no owner
    const two = toJson([ROW, { ...ROW2, owner: null }])
    expect(two.rows[1].owner).toBeNull()
    expect(JSON.stringify(two.rows[1])).not.toContain(MISSING)
  })
})

describe('inventoryExport — a column empty on every row is not shipped', () => {
  it('drops a never-collected column and records why', () => {
    const { columns, omitted } = selectColumns([
      { file: 'a.docx', owner: null }, { file: 'b.docx', owner: null },
    ])
    expect(columns.map((c) => c.key)).not.toContain('owner')
    expect(omitted.find((o) => o.key === 'owner').reason).toBe('never-collected')
  })

  it('distinguishes always-blank from never-collected', () => {
    const { omitted } = selectColumns([
      { file: 'a.docx', owner: '', path: null }, { file: 'b.docx', owner: '   ', path: null },
    ])
    expect(omitted.find((o) => o.key === 'owner').reason).toBe('always-blank')
    expect(omitted.find((o) => o.key === 'path').reason).toBe('never-collected')
  })

  it('keeps a column that any single row populates', () => {
    const { columns } = selectColumns([{ file: 'a.docx', owner: null }, { file: 'b.docx', owner: 'x@y' }])
    expect(columns.map((c) => c.key)).toContain('owner')
  })

  it('never drops the identity column, even with no rows at all', () => {
    const { columns } = selectColumns([])
    expect(columns.map((c) => c.key)).toEqual(['file'])
    const { csv } = toCsv([])
    expect(csv).toBe('file\r\n')
  })

  it('drops exclusion_reason on a discover-only run — it is written at Assess', () => {
    const { omitted } = selectColumns([ROW, ROW2])
    expect(omitted.map((o) => o.key)).toContain('exclusion_reason')
  })
})

describe('inventoryExport — the boundary and the instant travel with the rows', () => {
  it('stamps every row with the run and the snapshot instant', () => {
    const { csv } = toCsv([ROW, ROW2], { scanId: 'scan-1', takenAt: '2026-08-19T10:05:00Z' })
    const h = header(csv)
    dataRows(csv).map(cells).forEach((r) => {
      expect(r[h.indexOf('scan_id')]).toBe('scan-1')
      expect(r[h.indexOf('inventory_taken_at')]).toBe('2026-08-19T10:05:00Z')
    })
  })

  it('leaves the instant missing rather than substituting the export time', () => {
    const { csv } = toCsv([{ ...ROW, discovered_at: null }], { scanId: 'scan-1', takenAt: null })
    const h = header(csv)
    expect(h).not.toContain('inventory_taken_at')     // empty on every row → not shipped
    const doc = toJson([{ ...ROW, discovered_at: null }],
      { scanId: 'scan-1', takenAt: null, exportedAt: '2026-08-20T12:00:00Z' })
    expect(doc.inventory_taken_at).toBeNull()
    expect(doc.exported_at).toBe('2026-08-20T12:00:00Z')
  })

  it('names the run and the instant in the filename', () => {
    expect(exportFilename({ scanId: 'scan-1', takenAt: '2026-08-19T10:05:00Z' }))
      .toBe('acp-inventory-scan-1-20260819T100500Z.csv')
  })

  it('says time-not-recorded rather than dating the file to the click', () => {
    expect(exportFilename({ scanId: 'scan-1', takenAt: null }))
      .toBe('acp-inventory-scan-1-time-not-recorded.csv')
  })

  it('sanitises a scan id that would escape the filename', () => {
    expect(exportFilename({ scanId: '../../etc/passwd', takenAt: null }))
      .toBe('acp-inventory-etc-passwd-time-not-recorded.csv')
  })
})

describe('inventoryExport — CSV mechanics', () => {
  it('quotes and doubles per RFC 4180', () => {
    const { csv } = toCsv([{ ...ROW, file: 'Q1 "final", v2.docx' }])
    expect(dataRows(csv)[0]).toContain('"Q1 ""final"", v2.docx"')
    expect(cells(dataRows(csv)[0])[0]).toBe('Q1 "final", v2.docx')
  })

  it('keeps a newline inside a field readable to a CSV parser', () => {
    const { csv } = toCsv([{ ...ROW, lifecycle_reason: 'line one\nline two' }])
    // The record spans two physical lines but is one CSV row; the quote is what makes that true.
    expect(csv).toContain('"line one\nline two"')
  })

  it('preserves trailing whitespace in a name instead of letting a reader trim it', () => {
    const { csv } = toCsv([{ ...ROW, file: 'trailing space .docx' }])
    expect(cells(dataRows(csv)[0])[0]).toBe('trailing space .docx')
  })

  it('neutralises a formula-injection filename from the customer estate', () => {
    const { csv } = toCsv([{ ...ROW, file: '=HYPERLINK("http://evil","click")' }])
    expect(cells(dataRows(csv)[0])[0].startsWith("'=")).toBe(true)
  })

  it('does not mangle a negative number into text', () => {
    expect(csvValue(-3)).toBe('-3')
  })

  it('uses CRLF line endings', () => {
    const { csv } = toCsv([ROW])
    expect(csv.endsWith('\r\n')).toBe(true)
    expect(csv.split('\r\n').length).toBe(3)      // header, one row, trailing empty
  })
})

describe('inventoryExport — input shapes', () => {
  it('accepts the discoveryInventory envelope as well as a bare array', () => {
    expect(normalizeRows({ rows: [ROW], total: 1 })).toHaveLength(1)
    expect(normalizeRows([ROW])).toHaveLength(1)
  })

  it('keeps a failed read as null so a caller cannot export an empty estate by accident', () => {
    expect(normalizeRows(null)).toBeNull()
    expect(normalizeRows({ total: 4 })).toBeNull()
  })
})

describe('inventoryExport — the JSON manifest says what the file is not', () => {
  it('carries the phase, the no-findings statement and the legend', () => {
    const doc = toJson([ROW, ROW2], { scanId: 'scan-1', takenAt: '2026-08-19T10:05:00Z',
      takenAtSource: 'run.discovered_at', exportedAt: '2026-08-20T12:00:00Z' })
    expect(doc.phase).toBe('discover')
    expect(doc.contains).toMatch(/no file was opened/i)
    expect(doc.legend.csv_missing_token).toBe(MISSING)
    expect(doc.inventory_taken_at_source).toBe('run.discovered_at')
    expect(doc.row_count).toBe(2)
  })

  it('lists the columns it dropped, so the reader can tell considered from forgotten', () => {
    const doc = toJson([ROW, ROW2])
    expect(doc.omitted_columns.map((o) => o.key)).toContain('exclusion_reason')
    expect(doc.columns.map((c) => c.key)).toContain('lifecycle_status')
  })
})

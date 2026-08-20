// Taking the discovery inventory out of ACP.
//
// After a Discover run the operator has a list of what was found. This module turns that list
// into a file they can hand to somebody — CSV for a spreadsheet or an auditor, JSON for anything
// that will read it programmatically. Pure and React-free so vitest can exercise every rule
// below without a DOM.
//
// ── What may be in it, and why the column list is a WHITELIST ────────────────────────────────
//
// ADR 0020: Discover LISTS. It classifies from metadata (`classify_from_metadata` — mime/ext, no
// bytes), persists a `scan_inventory` row per file, and STOPS. It never opens a file. So this
// export may carry only what source metadata yields: name, path, format, size, owner, dates,
// the metadata classification, and the lifecycle tags a rule applied to the row.
//
// It must NOT carry findings, scores, conformance verdicts, page/image counts, or anything else
// that implies a file was read — those belong to Assess, which is a separate, explicitly
// triggered phase. `COLUMNS` below is therefore an allow-list rather than "whatever is on the
// row": a future field added to `scan_inventory`, or an assessed `file_records` row handed in by
// a caller that mixed the two, cannot leak into a customer-facing file by accident. `FORBIDDEN`
// names the assessed fields explicitly so the intent is greppable, and a test drives a row
// carrying all of them through the exporter to prove none survives.
//
// ADR 0016 is the same honesty in the other direction: a discovered-but-unassessed document has
// NO findings. Not zero findings. An export with a `findings` column full of `0` would state, in
// a spreadsheet, that ACP checked every file and found nothing wrong with any of them.
//
// ── Missing is not zero, and it is not blank either ──────────────────────────────────────────
//
// A metadata listing is ragged: SMB has no owner, a OneDrive listing has no `driveId`, a Drive
// folder can withhold `createdTime`. Rendering all of that as `""` — which is what the
// server-side `/scans/{id}/inventory.csv` does today — collapses three different facts into one
// cell:
//
//     the source reported no value at all      (discovery cannot know it)
//     the source reported an empty value       (discovery knows it, and it is blank)
//     the value is genuinely 0                 (a 0 KB file is a real, interesting fact)
//
// So: a missing value is written as the `MISSING` token, a genuinely blank one as an empty
// field, and `0` as `0`. The token is prose — it cannot be mistaken for data, and it survives a
// spreadsheet import as text. That does force a column like `size_kb` to import as text when any
// row is missing a size, and that is the correct trade: a missing size read as `0` is a lie about
// the estate, and it is the exact lie an auditor would act on.
//
// JSON has `null`, so it needs no token and carries the distinction natively. That is most of the
// reason both formats ship rather than CSV alone.
//
// ── An empty column is not shipped ───────────────────────────────────────────────────────────
//
// A column that is missing on every row tells the reader nothing and invites them to conclude the
// estate has no owners / no dates / nothing archived. It is dropped, and the manifest records
// that it was dropped and why — so the reader can tell "we considered this and had nothing" from
// "nobody thought of it". `file` is never dropped; a table with no identity column is not a table.

/** Written into a CSV cell for a value discovery did not collect. Prose, so it cannot be read
 *  as data, and distinct from an empty field (collected, and blank). */
export const MISSING = '(not collected)'

/** The column allow-list. Order is the column order in the file.
 *
 *  `kind` is documentation for the reader, not a coercion: nothing here is reformatted, because
 *  a re-formatted timestamp is a second version of a fact ACP already persisted. Dates are
 *  emitted exactly as the source recorded them (ISO-8601 from every connector).
 */
export const COLUMNS = [
  { key: 'file', header: 'file', kind: 'text', note: 'file name as the source reports it' },
  { key: 'path', header: 'path', kind: 'text', note: 'full path within the source' },
  { key: 'parent_folder', header: 'parent_folder', kind: 'text', note: 'containing folder' },
  { key: 'format', header: 'format', kind: 'text', note: 'derived from name + MIME, no bytes read' },
  { key: 'mime', header: 'mime', kind: 'text', note: 'MIME type the source reported' },
  { key: 'doc_class', header: 'doc_class', kind: 'text', note: 'classify_from_metadata — metadata only' },
  // Deliberately NOT called `status`. On the wire the route calls it that, and in a file whose
  // other columns are all inventory a bare "status" reads as a conformance verdict — the one
  // thing ADR 0020 says this export cannot contain. It is a projection from format alone
  // (assessable / metadata_only / unsupported / excluded), and the triage spec is explicit that
  // applicability before assessment is a projection and must be labelled one.
  { key: 'status', header: 'assessability_projected', kind: 'text',
    note: 'projected from format — whether Assess COULD evaluate this file. Not a verdict; nothing was opened' },
  { key: 'size_kb', header: 'size_kb', kind: 'number', note: 'size in KB as reported by the source' },
  { key: 'owner', header: 'owner', kind: 'text', note: 'owner recorded by the source' },
  { key: 'created_at', header: 'created_at', kind: 'text', note: "source's creation time" },
  { key: 'source_modified', header: 'source_modified', kind: 'text', note: "source's last-modified time" },
  { key: 'discovered_at', header: 'discovered_at', kind: 'text', note: 'when ACP first listed this file' },
  { key: 'lifecycle_status', header: 'lifecycle_status', kind: 'text', note: 'Active / Archive Candidate / …' },
  { key: 'lifecycle_rule_id', header: 'lifecycle_rule_id', kind: 'text', note: 'the rule that set the status' },
  { key: 'lifecycle_reason', header: 'lifecycle_reason', kind: 'text', note: 'why that rule matched' },
  { key: 'exclusion_reason', header: 'exclusion_reason', kind: 'text', note: 'why Assess skipped it (written at Assess)' },
  // The join key back to the system of record. A SharePoint item id is unique only WITHIN its
  // drive, so both halves travel or neither identifies anything.
  { key: 'drive_file_id', header: 'source_item_id', kind: 'text', note: 'item id in the source system' },
  { key: 'drive_id', header: 'source_drive_id', kind: 'text', note: 'drive the item was listed from (SharePoint)' },
  { key: 'checksum', header: 'checksum', kind: 'text',
    note: 'content fingerprint as reported by the source (ADR 0011) — computed by the source, not by opening the file here' },
  // The boundary travels with the rows. A file count is a fact about a boundary, not about an
  // estate (scanScope.js), and a CSV outlives the screen that explained it — so every row states
  // which run it came from and what instant that run's inventory describes.
  { key: 'scan_id', header: 'scan_id', kind: 'text', note: 'the discovery run these rows came from' },
  { key: 'inventory_taken_at', header: 'inventory_taken_at', kind: 'text',
    note: 'when this inventory was taken — every other column is only true as of this instant' },
]

/** Assessed fields that must never reach a discovery export. Named rather than merely omitted so
 *  the intent survives someone widening COLUMNS later; pinned by a test. */
export const FORBIDDEN = Object.freeze([
  'score', 'compliant', 'issues', 'findings', 'finding_count', 'outcome', 'engine',
  'skipped_rules', 'pages', 'sheets', 'remediated_at', 'published_at', 'acp_stamped',
  'drive_write_url', 'blob_url', 'severity', 'wcag', 'rule_id',
])

/** Never dropped, however empty: a table with no identity column is not a table. */
const ALWAYS_KEEP = new Set(['file'])

/** Did discovery record nothing at all here? `0` and `false` are values; only null/undefined and
 *  a non-finite number are absence. */
export const isMissing = (v) =>
  v === null || v === undefined || (typeof v === 'number' && !Number.isFinite(v))

/** Recorded, and empty. Distinct from missing — see the header. */
export const isBlank = (v) => typeof v === 'string' && v.trim() === ''

/** Accept either a bare array of rows or discoveryInventory.js's `{ rows, total }`. `null` (a
 *  failed read) stays null — the caller must not export a file that claims an empty estate. */
export function normalizeRows(input) {
  if (Array.isArray(input)) return input
  if (input && Array.isArray(input.rows)) return input.rows
  return null
}

/**
 * Which columns this export actually ships, and which it drops.
 *
 * A column survives if any row carries a real value for it. The two drop reasons are kept apart
 * because they mean different things to a reader: `never-collected` is a gap in what discovery
 * can see, `always-blank` is discovery seeing an empty value everywhere.
 */
export function selectColumns(rows, { columns = COLUMNS } = {}) {
  const list = rows || []
  const kept = []
  const omitted = []
  columns.forEach((col) => {
    if (ALWAYS_KEEP.has(col.key)) { kept.push(col); return }
    let anyPresent = false
    let anyNonBlank = false
    for (const r of list) {
      const v = r ? r[col.key] : undefined
      if (isMissing(v)) continue
      anyPresent = true
      if (!isBlank(v)) { anyNonBlank = true; break }
    }
    if (anyNonBlank) kept.push(col)
    else omitted.push({ key: col.key, header: col.header,
      reason: anyPresent ? 'always-blank' : 'never-collected' })
  })
  return { columns: kept, omitted }
}

// A leading =, +, -, @, tab or CR makes a spreadsheet treat the cell as a formula. Filenames and
// folder names come from the customer's estate, so they are untrusted input to whatever opens
// this file. Neutralised with a leading apostrophe (the spreadsheet convention for "this is
// text"), and only for strings — a negative number must stay a number.
const RISKY_PREFIX = /^[=+\-@\t\r]/
const neutralise = (s) => (RISKY_PREFIX.test(s) ? `'${s}` : s)

/** One value as it appears in a CSV field, before quoting. */
export function csvValue(v) {
  if (isMissing(v)) return MISSING
  if (typeof v === 'number') return String(v)
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  return neutralise(String(v))
}

// RFC 4180: quote when the field contains a quote, a delimiter or a line break, and double any
// embedded quote. Leading/trailing whitespace is quoted too, so a name that ends in a space
// survives the round trip instead of being trimmed by the reader.
const NEEDS_QUOTE = /[",\r\n]|^\s|\s$/
const quote = (s) => (NEEDS_QUOTE.test(s) ? `"${s.replace(/"/g, '""')}"` : s)

/**
 * The inventory as CSV. Rows only — no preamble, so `read_csv` and every spreadsheet open it
 * without a skiprows argument. The provenance a preamble would have carried instead rides in the
 * `scan_id` / `inventory_taken_at` columns, in the filename, and in the JSON manifest.
 *
 * CRLF line endings, per RFC 4180 and because Excel on Windows is the destination that punishes
 * bare LF.
 */
export function toCsv(input, { takenAt = null, scanId = null } = {}) {
  const rows = normalizeRows(input) || []
  const decorated = rows.map((r) => decorate(r, { takenAt, scanId }))
  const sel = selectColumns(decorated)
  const lines = [sel.columns.map((c) => quote(c.header)).join(',')]
  decorated.forEach((r) => {
    lines.push(sel.columns.map((c) => quote(csvValue(r[c.key]))).join(','))
  })
  return { csv: lines.join('\r\n') + '\r\n', columns: sel.columns, omitted: sel.omitted,
    rowCount: decorated.length }
}

// Stamp the run-level facts onto each row. `takenAt` null means the run's discovery-completion
// time is not recorded (see discoverRunTime.js) — it stays missing rather than being filled with
// the export time, which would date the snapshot to whenever somebody happened to click.
function decorate(row, { takenAt, scanId }) {
  const out = {}
  COLUMNS.forEach((c) => { out[c.key] = row ? row[c.key] : undefined })
  out.scan_id = (row && row.scan_id) ?? scanId ?? undefined
  out.inventory_taken_at = takenAt ?? undefined
  return out
}

/** The JSON form: the same rows, plus the manifest that says what this file is and is not.
 *  `null` here means exactly what `MISSING` means in the CSV, natively. */
export function toJson(input, { takenAt = null, takenAtSource = null, scanId = null,
  exportedAt = null } = {}) {
  const rows = normalizeRows(input) || []
  const decorated = rows.map((r) => decorate(r, { takenAt, scanId }))
  const sel = selectColumns(decorated)
  return {
    artifact: 'acp-discovery-inventory',
    version: 1,
    scan_id: scanId ?? null,
    // WHEN THE INVENTORY WAS TAKEN — the instant every row describes.
    inventory_taken_at: takenAt ?? null,
    inventory_taken_at_source: takenAtSource ?? null,
    // WHEN THIS FILE WAS WRITTEN. A different fact, and never a substitute for the one above.
    exported_at: exportedAt ?? null,
    row_count: decorated.length,
    phase: 'discover',
    contains: 'source metadata only — no file was opened (ADR 0020). No findings, scores or '
      + 'conformance verdicts: a discovered file has no assessment, which is not the same as a '
      + 'clean one (ADR 0016).',
    legend: {
      null: 'discovery did not collect this value',
      '""': 'discovery collected the value and it was empty',
      csv_missing_token: MISSING,
    },
    columns: sel.columns.map((c) => ({ key: c.key, header: c.header, note: c.note })),
    omitted_columns: sel.omitted,
    rows: decorated.map((r) => {
      const o = {}
      sel.columns.forEach((c) => { o[c.header] = isMissing(r[c.key]) ? null : r[c.key] })
      return o
    }),
  }
}

// Dots are dropped along with the separators, not merely the slashes: a scan id is hex or a uuid,
// so nothing legitimate is lost, and `../..` sanitised to `..-..` is a filename that still reads
// as a traversal attempt to whoever receives the file.
const SAFE = (s) => String(s ?? '').replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '')
const compact = (iso) => {
  const t = Date.parse(iso)
  return Number.isFinite(t) ? new Date(t).toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z') : null
}
/** A filename an operator can still identify a year later: which run, and as of when. A null
 *  `takenAt` becomes `time-not-recorded` rather than the export time — the filename must not
 *  assert a snapshot instant the backend never persisted. */
export function exportFilename({ scanId = null, takenAt = null, ext = 'csv' } = {}) {
  const when = takenAt ? compact(takenAt) : null
  return ['acp-inventory', SAFE(scanId) || 'unknown-scan', when || 'time-not-recorded']
    .join('-') + `.${ext}`
}

/** The blob + filename for a download, without touching the DOM — so a test can assert the bytes
 *  and a component can hand them to whatever it uses to save a file. */
export function csvBlob(input, opts = {}) {
  const { csv, omitted, columns, rowCount } = toCsv(input, opts)
  // The BOM is what makes Excel read UTF-8 rather than the local ANSI codepage; without it a
  // customer's non-ASCII filenames arrive mojibaked in the tool most of them will open this in.
  return { blob: new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' }),
    filename: exportFilename({ ...opts, ext: 'csv' }), omitted, columns, rowCount }
}

export function jsonBlob(input, opts = {}) {
  const manifest = toJson(input, opts)
  return { blob: new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json;charset=utf-8' }),
    filename: exportFilename({ ...opts, ext: 'json' }), omitted: manifest.omitted_columns,
    columns: manifest.columns, rowCount: manifest.row_count }
}

/** Hand a blob to the browser as a download. Split out so the exporters above stay pure and the
 *  component can inject a stub in tests. */
export function saveBlob(blob, filename, { dom = typeof document === 'undefined' ? null : document } = {}) {
  if (!dom) return false
  const url = URL.createObjectURL(blob)
  const a = dom.createElement('a')
  a.href = url
  a.download = filename
  dom.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  return true
}

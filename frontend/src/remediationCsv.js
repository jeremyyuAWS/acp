// R20 · CSV companion to the remediation report (the PDF is exportRemediationReport in pdfReport.js).
//
// Same data, same source of truth: this builds the SAME `buildRemediationModel` the PDF uses, so the
// two exports can never disagree about what was found, fixed, and what remains. Where the PDF is the
// human-readable record + verification checklist, the CSV is the machine-readable row-per-change table
// a customer can pull into their own tracker.
//
// One row per (document × success criterion) — the same "one checkbox per criterion, not per image"
// granularity the model already collapses to. Honesty carried over from the PDF: a change with no
// recorded write time reads "time not recorded", never a substituted timestamp; a truncated (capped)
// fix list is flagged, not silently presented as complete.
import { WCAG } from './wcagCatalog.js'
import { buildRemediationModel } from './reportModel.js'

// RFC-4180 field quoting: wrap in double-quotes and double any embedded quote when the value contains
// a comma, quote, CR or LF. A before/after value routinely contains all of these.
function _cell(v) {
  const s = v == null ? '' : String(v)
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export const CSV_COLUMNS = [
  'Document', 'Folder', 'Format',
  'Success criterion', 'Criterion name', 'Category',
  'Before', 'After', 'Note',
  'Applied at', 'Document remediated at', 'Awaiting review (document)',
]

// Flat row objects, one per change — exported separately so tests (and any other consumer) can assert
// the data without parsing CSV text.
export function remediationCsvRows(model) {
  const rows = []
  for (const doc of model.documents || []) {
    for (const it of doc.items || []) {
      rows.push({
        Document: doc.name,
        Folder: doc.dir || '(root)',
        Format: `.${doc.fmt}`,
        'Success criterion': it.sc,
        'Criterion name': it.name || '',
        Category: it.category || '',
        Before: it.before == null ? '' : it.before,
        After: it.after == null ? '' : it.after,
        Note: it.note || '',
        // The model stamps `at` only where the applied-fix record joined; mirror the PDF's wording.
        'Applied at': it.at || 'time not recorded',
        'Document remediated at': doc.remediatedAt || 'time not recorded',
        'Awaiting review (document)': doc.awaiting || 0,
      })
    }
  }
  return rows
}

// The full CSV text. Leads with a `# PARTIAL …` comment line when the fix list was capped, so the
// truncation travels with the file rather than living only in the UI that generated it.
export function remediationCsvText(model) {
  const rows = remediationCsvRows(model)
  const lines = []
  if (model.partial) {
    lines.push(`# PARTIAL: server returned the maximum of ${model.partial} fix records; changes beyond that are not listed. Re-run against a narrower scan for the remainder.`)
  }
  lines.push(CSV_COLUMNS.map(_cell).join(','))
  for (const r of rows) lines.push(CSV_COLUMNS.map((c) => _cell(r[c])).join(','))
  return lines.join('\r\n') + '\r\n'
}

// Build the model from the same inputs exportRemediationReport takes, serialize, and hand back the
// text + a default filename. Kept free of DOM so it is unit-testable; the caller triggers the download.
export function buildRemediationCsv(d = {}) {
  const scNames = Object.fromEntries(WCAG.map((w) => [w.sc, w.name]))
  const model = buildRemediationModel({ ...d, scNames })
  const org = (model.org || 'remediation').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  return { text: remediationCsvText(model), filename: d.filename || `${org || 'remediation'}-changes.csv`, model }
}

// Browser entry point — mirrors exportRemediationReport's signature so the button wiring is symmetric.
export function downloadRemediationCsv(d = {}) {
  const { text, filename } = buildRemediationCsv(d)
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
  return filename
}

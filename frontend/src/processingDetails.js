// Per-file rows for the live "Processing details" table (progress redesign, slice 3). Pure: turns the
// scan's live file_records (get_scan streams one as each file lands) into display rows — format, result,
// a semantic kind. In-flight files are NOT individually named by the backend (the fan-out is parallel,
// so no single "file N in flight" is knowable — see App.jsx queuedProgress), so the table shows the
// files that have LANDED; the still-processing COUNT is surfaced separately.
import { fmtOf } from './capability.js'

// Map a file record to a display result + semantic kind.
// "Failed" is deliberately avoided: it is ambiguous between "ACP failed to process it" and
// "the document failed its accessibility check". Use unambiguous operational language instead.
function resultOf(f) {
  if (f.status === 'error') return { label: "Couldn't assess", kind: 'bad' }
  if (f.status === 'certifiable') return { label: 'Assessed — no issues', kind: 'ok' }
  if (f.status === 'uncertain') return { label: 'Assessed — issues found', kind: 'warn' }
  if (f.status === 'discovered') return { label: 'Queued', kind: 'muted' }
  // 'analysed' = file was opened and scored; check the issues array for the right label.
  if (f.status === 'analysed') {
    return (f.issues && f.issues.length)
      ? { label: 'Assessed — issues found', kind: 'warn' }
      : { label: 'Assessed — no issues', kind: 'ok' }
  }
  // Any other backend state (e.g. 'processing', 'queued') falls through to the literal value.
  return { label: f.status || 'Processing', kind: 'muted' }
}

// The action available for a row, expressed as a verb the caller can render as a button.
// 'view'  → file was assessed; show its results.
// 'error' → file couldn't be assessed; show the error detail.
// null    → still in flight; no actionable outcome yet.
function actionOf(f) {
  if (f.status === 'error') return 'error'
  if (f.status === 'certifiable' || f.status === 'uncertain' || f.status === 'analysed') return 'view'
  return null
}

// A Drive folder value is a long opaque ID (only alphanumeric/dash/underscore, no slashes).
// SharePoint paths contain '/' and local paths are short readable names — only the Drive case
// is meaningless to display, so suppress it rather than showing a hash to the user.
function folderOf(f) {
  const v = f.parent_folder || null
  if (!v) return null
  if (/^[A-Za-z0-9_-]{20,}$/.test(v)) return null
  return v
}

export function processingRows(files) {
  return (files || []).map((f) => {
    const r = resultOf(f)
    return {
      file: f.file,
      format: (fmtOf(f) || '').toUpperCase(),
      status: f.status,
      result: r.label,
      kind: r.kind,
      score: typeof f.score === 'number' ? f.score : null,
      issues: Array.isArray(f.issues) ? f.issues.length : null,
      folder: folderOf(f),
      owner: f.owner || null,
      action: actionOf(f),
    }
  })
}

export const PROCESSING_FILTERS = [
  { key: 'all',      label: 'All' },
  { key: 'findings', label: 'Findings' },
  { key: 'failed',   label: "Couldn't assess" },
  { key: 'completed', label: 'Completed' },
]

// 'completed' = anything that has landed with a real result (not the discovered placeholder).
const MATCH = {
  all: () => true,
  findings: (r) => r.status === 'uncertain',
  failed:   (r) => r.status === 'error',
  completed: (r) => r.status !== 'discovered',
}

export function filterRows(rows, key) {
  return (rows || []).filter(MATCH[key] || MATCH.all)
}

export function filterCounts(rows) {
  return PROCESSING_FILTERS.reduce((acc, { key }) => {
    acc[key] = (rows || []).filter(MATCH[key]).length
    return acc
  }, {})
}

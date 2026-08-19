// Per-file rows for the live "Processing details" table (progress redesign, slice 3). Pure: turns the
// scan's live file_records (get_scan streams one as each file lands) into display rows — format, result,
// a semantic kind. In-flight files are NOT individually named by the backend (the fan-out is parallel,
// so no single "file N in flight" is knowable — see App.jsx queuedProgress), so the table shows the
// files that have LANDED; the still-processing COUNT is surfaced separately.
import { fmtOf } from './capability.js'

// file_records.status → how it reads in the table. certifiable = clean pass (compliant); uncertain =
// a human needs to look; error = failed to process; discovered = an inventory placeholder (Discover
// only, nothing opened yet).
const RESULT = {
  certifiable: { label: 'Passed', kind: 'ok' },
  uncertain: { label: 'Needs review', kind: 'warn' },
  error: { label: 'Failed', kind: 'bad' },
  discovered: { label: 'Queued', kind: 'muted' },
}

export function processingRows(files) {
  return (files || []).map((f) => {
    const r = RESULT[f.status] || { label: f.status || '—', kind: 'muted' }
    return {
      file: f.file,
      format: (fmtOf(f) || '').toUpperCase(),
      status: f.status,
      result: r.label,
      kind: r.kind,
      score: typeof f.score === 'number' ? f.score : null,
    }
  })
}

export const PROCESSING_FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'findings', label: 'Findings' },
  { key: 'failed', label: 'Failed' },
  { key: 'completed', label: 'Completed' },
]

// 'completed' = anything that has landed with a real result (not the discovered placeholder).
const MATCH = {
  all: () => true,
  findings: (r) => r.status === 'uncertain',
  failed: (r) => r.status === 'error',
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

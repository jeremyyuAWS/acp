import { useState } from 'react'
import { processingRows, filterRows, filterCounts, PROCESSING_FILTERS } from './processingDetails.js'

const KIND_COLOR = { ok: '#2F7D51', warn: '#9A6011', bad: '#A5314A', muted: '#54636F' }
const cell = { padding: '3px 8px', borderTop: '1px solid var(--line, #eceff4)', whiteSpace: 'nowrap' }

// Sort comparators keyed by column. null score sorts after numeric scores.
const SORT = {
  file:   (a, b) => a.file.localeCompare(b.file),
  format: (a, b) => (a.format || '').localeCompare(b.format || ''),
  result: (a, b) => a.result.localeCompare(b.result),
  score:  (a, b) => {
    if (a.score == null && b.score == null) return 0
    if (a.score == null) return 1
    if (b.score == null) return -1
    return b.score - a.score   // higher score first
  },
}

function SortTh({ col, label, sort, onSort, style }) {
  const active = sort.col === col
  const arrow = active ? (sort.asc ? ' ↑' : ' ↓') : ''
  return (
    <th scope="col"
        onClick={() => onSort(col)}
        style={{ textAlign: style?.textAlign || 'left', padding: '4px 8px',
                 borderBottom: '1px solid var(--line, #e4e7ef)',
                 color: active ? 'var(--plum, #46303F)' : '#54636F',
                 fontWeight: 600, cursor: 'pointer', userSelect: 'none',
                 whiteSpace: 'nowrap', ...style }}>
      {label}{arrow}
    </th>
  )
}

function applySort(rows, { col, asc }) {
  if (!col || !SORT[col]) return rows
  const sorted = [...rows].sort(SORT[col])
  return asc ? sorted : sorted.reverse()
}

export default function ProcessingDetails({ files, processing = 0, defaultOpen = false }) {
  const [filter, setFilter] = useState('all')
  const [sort, setSort] = useState({ col: null, asc: true })
  const rows = processingRows(files)
  if (rows.length === 0 && processing === 0) return null
  const counts = filterCounts(rows)
  const filtered = filterRows(rows, filter)
  const shown = applySort(filtered, sort)

  const onSort = (col) => setSort((s) => s.col === col ? { col, asc: !s.asc } : { col, asc: true })

  return (
    <details className="procdetails" style={{ marginTop: 8 }} open={defaultOpen || undefined}>
      <summary style={{ cursor: 'pointer', fontSize: 12.5, color: '#54636F' }}>
        View processing details ({rows.length} landed{processing ? ` · ${processing} processing` : ''})
      </summary>
      <div role="tablist" aria-label="Filter files" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '8px 0' }}>
        {PROCESSING_FILTERS.map(({ key, label }) => (
          <button key={key} role="tab" aria-selected={filter === key}
                  className={filter === key ? 'fchip on' : 'fchip'}
                  onClick={() => setFilter(key)}>{label} {counts[key]}</button>
        ))}
      </div>
      <div style={{ overflowX: 'auto', maxHeight: 260, overflowY: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 12.5, width: '100%' }}>
          <caption className="sronly">Per-file processing status for the current scan.</caption>
          <thead>
            <tr>
              <SortTh col="file"   label="File"     sort={sort} onSort={onSort} />
              <SortTh col="format" label="Format"   sort={sort} onSort={onSort} />
              <th scope="col" style={{ textAlign: 'left', padding: '4px 8px',
                                       borderBottom: '1px solid var(--line, #e4e7ef)',
                                       color: '#54636F', fontWeight: 600 }}>Location</th>
              <th scope="col" style={{ textAlign: 'left', padding: '4px 8px',
                                       borderBottom: '1px solid var(--line, #e4e7ef)',
                                       color: '#54636F', fontWeight: 600 }}>Owner</th>
              <SortTh col="result" label="Result"   sort={sort} onSort={onSort} />
              <SortTh col="score"  label="Score"    sort={sort} onSort={onSort} style={{ textAlign: 'right' }} />
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.file}>
                <td style={{ ...cell, fontFamily: 'ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace', fontSize: 11.5 }}>{r.file}</td>
                <td style={cell}>{r.format || '—'}</td>
                <td style={{ ...cell, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', color: '#54636F' }}
                    title={r.location || undefined}>{r.location || '—'}</td>
                <td style={{ ...cell, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', color: '#54636F' }}
                    title={r.owner || undefined}>{r.owner || '—'}</td>
                <td style={{ ...cell, color: KIND_COLOR[r.kind], fontWeight: 500 }}>{r.result}</td>
                <td style={{ ...cell, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                  {r.score == null ? '—' : r.score}
                </td>
              </tr>
            ))}
            {shown.length === 0 && (
              <tr><td colSpan={6} style={{ ...cell, color: '#8891A3' }}>Nothing in this view yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {processing > 0 && (
        <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>
          {processing} more file{processing === 1 ? '' : 's'} still processing — they appear here as they finish.
        </p>
      )}
    </details>
  )
}

import { useState } from 'react'
import { processingRows, filterRows, filterCounts, PROCESSING_FILTERS } from './processingDetails.js'

const KIND_COLOR = { ok: '#2F7D51', warn: '#9A6011', bad: '#A5314A', muted: '#54636F' }
const cell = { padding: '3px 8px', borderTop: '1px solid var(--line, #eceff4)', whiteSpace: 'nowrap' }

// Background + text for each format pill. Muted but distinct — enough contrast to scan
// a column of mixed formats without being loud beside the status colours.
const FMT_PILL = {
  DOCX: { bg: '#DBEAFE', fg: '#1D4ED8' },   // blue  — Word
  PDF:  { bg: '#FEE2E2', fg: '#B91C1C' },   // red   — Acrobat
  PPTX: { bg: '#FFEDD5', fg: '#C2410C' },   // orange — PowerPoint
  XLSX: { bg: '#DCFCE7', fg: '#15803D' },   // green  — Excel
}

function FormatPill({ fmt }) {
  if (!fmt) return <span style={{ color: '#8891A3' }}>—</span>
  const p = FMT_PILL[fmt]
  if (!p) return <span>{fmt}</span>
  return (
    <span style={{ display: 'inline-block', padding: '1px 7px', borderRadius: 10,
                   fontSize: 11, fontWeight: 600, letterSpacing: 0.2,
                   background: p.bg, color: p.fg }}>
      {fmt}
    </span>
  )
}

// Sort comparators keyed by column. null score/issues sort after numeric values.
const SORT = {
  file:   (a, b) => a.file.localeCompare(b.file),
  format: (a, b) => (a.format || '').localeCompare(b.format || ''),
  result: (a, b) => a.result.localeCompare(b.result),
  score:  (a, b) => {
    if (a.score == null && b.score == null) return 0
    if (a.score == null) return 1
    if (b.score == null) return -1
    return b.score - a.score
  },
  issues: (a, b) => {
    if (a.issues == null && b.issues == null) return 0
    if (a.issues == null) return 1
    if (b.issues == null) return -1
    return b.issues - a.issues
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

// Action label for a row's action verb.
const ACTION_LABEL = { view: 'View results', error: 'See error' }

export default function ProcessingDetails({ files, processing = 0, defaultOpen = false, onSelect }) {
  const [filter, setFilter] = useState('all')
  const [sort, setSort] = useState({ col: null, asc: true })
  const rows = processingRows(files)
  if (rows.length === 0 && processing === 0) return null
  const counts = filterCounts(rows)
  const filtered = filterRows(rows, filter)
  const shown = applySort(filtered, sort)

  const onSort = (col) => setSort((s) => s.col === col ? { col, asc: !s.asc } : { col, asc: true })

  // Hide Owner column when every visible row has the same owner (or none) — the column adds
  // no value when it repeats the same name on every line. The check is over ALL rows so the
  // column doesn't appear/disappear as the user switches filters.
  const ownerValues = new Set(rows.map((r) => r.owner).filter(Boolean))
  const showOwner = ownerValues.size > 1

  // Column count: Document + Format + Status + Score + Issues + (Owner?) + Action
  const colCount = 6 + (showOwner ? 1 : 0)

  return (
    <details className="procdetails" style={{ marginTop: 8 }} open={defaultOpen || undefined}>
      <summary style={{ cursor: 'pointer', fontSize: 12.5, color: '#54636F' }}>
        View processing details ({rows.length} landed{processing ? ` · ${processing} processing` : ''})
      </summary>
      {/* Filter group — aria-pressed toggles, not tabs (consistent with AssessWorklist). */}
      <div role="group" aria-label="Filter files" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '8px 0' }}>
        {PROCESSING_FILTERS.map(({ key, label }) => (
          <button key={key} type="button"
                  aria-pressed={filter === key}
                  className={filter === key ? 'fchip on' : 'fchip'}
                  onClick={() => setFilter(key)}>{label}{' '}{counts[key]}</button>
        ))}
      </div>
      <div style={{ overflowX: 'auto', maxHeight: 260, overflowY: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 12.5, width: '100%' }}>
          <caption className="sronly">Per-file processing status for the current scan.</caption>
          <thead>
            <tr>
              <SortTh col="file"   label="Document" sort={sort} onSort={onSort} style={{ width: '40%', minWidth: 200 }} />
              <SortTh col="format" label="Format"   sort={sort} onSort={onSort} />
              <SortTh col="result" label="Status"   sort={sort} onSort={onSort} />
              <SortTh col="score"  label="Score"    sort={sort} onSort={onSort} style={{ textAlign: 'right' }} />
              <SortTh col="issues" label="Issues"   sort={sort} onSort={onSort} style={{ textAlign: 'right' }} />
              {showOwner && (
                <th scope="col" style={{ textAlign: 'left', padding: '4px 8px',
                                         borderBottom: '1px solid var(--line, #e4e7ef)',
                                         color: '#54636F', fontWeight: 600 }}>Owner</th>
              )}
              <th scope="col" style={{ padding: '4px 8px', borderBottom: '1px solid var(--line, #e4e7ef)',
                                       color: '#54636F', fontWeight: 600 }}>
                <span className="sronly">Action</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => {
              const name = r.file.split('/').pop() || r.file
              return (
                <tr key={r.file}>
                  <td style={{ ...cell, maxWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    <span style={{ fontFamily: 'ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace', fontSize: 11.5 }}
                          title={r.file}>{name}</span>
                    {r.folder && (
                      <div style={{ fontSize: 10.5, color: '#8891A3', marginTop: 1, overflow: 'hidden',
                                    textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                           title={r.folder}>{r.folder}</div>
                    )}
                  </td>
                  <td style={cell}><FormatPill fmt={r.format} /></td>
                  <td style={{ ...cell, color: KIND_COLOR[r.kind], fontWeight: 500 }}>{r.result}</td>
                  <td style={{ ...cell, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {r.score == null ? '—' : r.score}
                  </td>
                  <td style={{ ...cell, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {r.issues == null ? '—' : r.issues}
                  </td>
                  {showOwner && (
                    <td style={{ ...cell, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', color: '#54636F' }}
                        title={r.owner || undefined}>{r.owner || '—'}</td>
                  )}
                  <td style={{ ...cell, paddingRight: 4 }}>
                    {r.action && (
                      <button type="button"
                              onClick={() => onSelect?.(r)}
                              style={{ fontSize: 11.5, padding: '2px 7px', borderRadius: 4,
                                       border: '1px solid var(--line, #e4e7ef)',
                                       background: 'transparent', cursor: 'pointer',
                                       color: r.action === 'error' ? KIND_COLOR.bad : 'var(--ink)',
                                       whiteSpace: 'nowrap' }}>
                        {ACTION_LABEL[r.action]}
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
            {shown.length === 0 && (
              <tr><td colSpan={colCount} style={{ ...cell, color: '#8891A3' }}>Nothing in this view yet.</td></tr>
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

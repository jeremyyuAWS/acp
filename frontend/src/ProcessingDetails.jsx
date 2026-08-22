import { useState } from 'react'
import { processingRows, filterRows, filterCounts, PROCESSING_FILTERS } from './processingDetails.js'

// The expandable "Processing details" table — per-file transparency during a live run, without forcing
// every user to watch a scrolling event log (the user's spec). Collapsed behind a toggle by default;
// technical users open it, everyone else ignores it. `processing` is the count of files not yet landed
// (their names are not knowable mid-fan-out), shown as a footer note rather than fabricated rows.
const KIND_COLOR = { ok: '#2F7D51', warn: '#9A6011', bad: '#A5314A', muted: '#54636F' }
const cellHead = { textAlign: 'left', padding: '4px 8px', borderBottom: '1px solid var(--line, #e4e7ef)', color: '#54636F', fontWeight: 600 }
const cell = { padding: '3px 8px', borderTop: '1px solid var(--line, #eceff4)', whiteSpace: 'nowrap' }

export default function ProcessingDetails({ files, processing = 0, defaultOpen = false }) {
  const [filter, setFilter] = useState('all')
  const rows = processingRows(files)
  if (rows.length === 0 && processing === 0) return null
  const counts = filterCounts(rows)
  const shown = filterRows(rows, filter)
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
              <th scope="col" style={cellHead}>File</th>
              <th scope="col" style={cellHead}>Format</th>
              <th scope="col" style={cellHead}>Location</th>
              <th scope="col" style={cellHead}>Owner</th>
              <th scope="col" style={cellHead}>Result</th>
              <th scope="col" style={{ ...cellHead, textAlign: 'right' }}>Score</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.file}>
                <td style={cell}>{r.file}</td>
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

import { useState, useEffect } from 'react'
import { getTableStructure } from './api.js'

// The docx table(s) as review evidence for a header-association finding (1.3.1): the REAL cell text as
// a grid with the header row highlighted, and whether that row is actually MARKED so a screen reader
// announces it for each data cell. Fetched on demand (mirrors HeadingOutline); renders the caller's
// honest fallback while loading or when no qualifying table exists — never a fabricated grid.

function TablePreview({ table }) {
  const { rows = [], headerRow = 0, headerMarked, truncated } = table
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ overflowX: 'auto', border: '1px solid var(--line,#e2dce4)', borderRadius: 8 }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
          <tbody>
            {rows.map((cells, ri) => {
              const isHeader = ri === headerRow
              const Cell = isHeader ? 'th' : 'td'
              return (
                <tr key={ri}>
                  {cells.map((c, ci) => (
                    <Cell key={ci} scope={isHeader ? 'col' : undefined}
                          style={{ border: '1px solid var(--line,#e2dce4)', padding: '5px 9px', textAlign: 'left',
                                   fontWeight: isHeader ? 700 : 400,
                                   background: isHeader ? 'var(--surface-2,#f0eef3)' : 'transparent',
                                   whiteSpace: 'nowrap', maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {c || (isHeader ? <span className="muted">(empty)</span> : '')}
                    </Cell>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ fontSize: 11.5, margin: '6px 0 0' }}>
        {headerMarked
          ? 'The highlighted row is marked as the header, so a screen reader announces it for each data cell.'
          : 'The highlighted row reads as the header — but it isn’t marked as one, so a screen reader won’t announce it for the data cells. Marking it is the fix.'}
        {truncated ? ' (Table trimmed for preview.)' : ''}
      </p>
    </div>
  )
}

export default function TableStructure({ scanId, file, wcag, fallback = null }) {
  const [tables, setTables] = useState(undefined)   // undefined = loading, null = none, array = tables
  useEffect(() => {
    let live = true
    setTables(undefined)
    getTableStructure(scanId, file).then((t) => { if (live) setTables(t || null) })
    return () => { live = false }
  }, [scanId, file])

  if (Array.isArray(tables) && tables.length) {
    return (
      <div className="ba-evidence ba-table">
        <p className="muted" style={{ fontSize: 12.5, margin: '0 0 8px' }}>
          {wcag ? `${wcag} — ` : ''}The table{tables.length > 1 ? 's' : ''} and {tables.length > 1 ? 'their' : 'its'} header row:
        </p>
        {tables.map((t, i) => <TablePreview key={i} table={t} />)}
      </div>
    )
  }
  return fallback
}

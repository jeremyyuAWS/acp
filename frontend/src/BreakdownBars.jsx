import { useState } from 'react'
import BucketFiles from './BucketFiles.jsx'

// The bar rows under BY FILE TYPE / BY CONTENT TYPE / BY AGE / BY SIZE, with the bucket's files
// one click away.
//
// A row is a real <button> rather than a div with an onClick, so it is reachable by Tab, activated
// by Enter and Space, and announced as expandable. `aria-expanded` and `aria-controls` tie it to
// the list it opens. The visual grid is unchanged — the button carries the same three columns the
// plain rows had, so nothing shifts for a reader who never clicks.
//
// A bucket with no member rows to show stays a plain row: an inert button that opens an empty
// panel is a worse answer than not offering the affordance.

export const chartPercent = (count, base) => count > 0 && base > 0 && count / base * 100 < 0.1 ? '<0.1' : (base > 0 ? count / base * 100 : 0).toFixed(1)

export default function BreakdownBars({
  buckets, columns, colorOf, membersOf = null, idPrefix, denominator = null,
}) {
  const [open, setOpen] = useState(null)
  const hasBase = Number.isFinite(denominator) && denominator >= 0
  const max = hasBase ? Math.max(1, denominator) : Math.max(1, ...buckets.map((b) => b.count))

  return buckets.map((b) => {
    const rows = membersOf ? (membersOf(b) || []) : null
    const clickable = Array.isArray(rows) && rows.length > 0
    const panelId = `${idPrefix}-${b.key}`
    const isOpen = open === b.key

    const cells = <>
      <span className="critlabel" style={{ fontSize: 13, textAlign: 'left',
                                           color: b.known === false ? 'var(--muted)' : undefined }}>
        {b.label}
      </span>
      <span className="track">
        <i style={{ width: `${(b.count / max) * 100}%`, background: colorOf(b) }} />
      </span>
      <span style={{ textAlign: 'right', fontSize: 13 }}>{b.count.toLocaleString()}{hasBase && ` · ${chartPercent(b.count, denominator)}%`}</span>
    </>

    return (
      <div key={b.key}>
        {clickable ? (
          <button
            type="button"
            className="critrow"
            aria-expanded={isOpen}
            aria-controls={panelId}
            onClick={() => setOpen(isOpen ? null : b.key)}
            style={{ gridTemplateColumns: columns, width: '100%', background: 'none',
                     border: 0, padding: '2px 0', font: 'inherit', cursor: 'pointer',
                     textAlign: 'inherit' }}
          >
            {cells}
          </button>
        ) : (
          <div className="critrow" style={{ gridTemplateColumns: columns }}>{cells}</div>
        )}
        {clickable && isOpen && (
          <BucketFiles id={panelId} bucket={b} rows={rows} onClose={() => setOpen(null)} />
        )}
      </div>
    )
  })
}

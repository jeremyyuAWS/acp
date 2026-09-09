import { useEffect, useRef } from 'react'
import { assessmentFor } from './capability.js'
import { WCAG } from './wcagCatalog.js'

const names = Object.fromEntries(WCAG.map(criterion => [criterion.sc, criterion.name]))
const cell = { padding: '9px 10px', textAlign: 'left', verticalAlign: 'top', borderBottom: '1px solid var(--line)' }

export default function AssessIncompleteChecks({ id, rows, assessment, onClose }) {
  const heading = useRef(null)
  // Read the same per-document bucket summed by the tile, not findings or a new estimate.
  const checks = rows.filter(row => row.opened).flatMap(row =>
    row.unassessableCriteria.map(sc => ({ row, sc })))
  useEffect(() => { heading.current?.focus() }, [])
  return <section id={id} role="region" aria-labelledby={`${id}-title`}
    onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); onClose() } }}
    style={{ marginTop: 16, padding: 16, border: '1px solid var(--line)', borderRadius: 12 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', gap: 12 }}>
      <h3 id={`${id}-title`} ref={heading} tabIndex={-1} style={{ margin: 0 }}>Checks not completed</h3>
      <button type="button" className="ghost small" onClick={onClose}>Close breakdown</button>
    </div>
    <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.5 }}>
      {checks.length ? <>{checks.length.toLocaleString()} checks across {new Set(checks.map(check => check.row.file)).size.toLocaleString()} documents.
        {' '}Each row is one selected criterion for one document. These results are unknown, not passed or failed.</>
        : 'No checks are in this bucket for the current assessment.'}
    </p>
    {checks.length > 0 && <div role="region" tabIndex={0} aria-label="Incomplete checks list"
      style={{ overflow: 'auto', maxHeight: 400 }}>
      <table style={{ width: '100%', minWidth: 560, borderCollapse: 'collapse', fontSize: 12.5 }}>
        <thead><tr>{['Check', 'Document', 'Format', 'Why not completed'].map(label =>
          <th key={label} scope="col" style={cell}>{label}</th>)}</tr></thead>
        <tbody>{checks.map(({ row, sc }, index) => <tr key={`${row.file}:${sc}:${index}`}>
          <th scope="row" style={cell}>WCAG {sc}{names[sc] && <div style={{ fontWeight: 400 }}>{names[sc]}</div>}</th>
          <td style={{ ...cell, overflowWrap: 'anywhere' }}>{row.file || row.name}</td>
          <td style={cell}>{String(row.fmt || 'Unknown').toUpperCase()}</td>
          <td style={cell}>{assessmentFor(assessment, row.fmt, sc) === 'human'
            ? 'Manual assessment required for this criterion and document format.'
            : 'No ACP assessment method is recorded for this criterion and document format.'}</td>
        </tr>)}</tbody>
      </table>
    </div>}
  </section>
}

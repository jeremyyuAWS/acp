import { useState } from 'react'
import { REMEDIATION_CATEGORIES, categoryLabel, countOf, remediationCategory, typeOf } from './remediationCategories.js'
import { WCAG } from './wcagCatalog.js'
import { scOf } from './fixSummary.js'
const names = Object.fromEntries(WCAG.map(row => [row.sc, row.name]))

export function FindingGroups({ rows = [] }) {
  const formats = new Map()
  for (const row of rows) {
    const fmt = typeOf(row.file)
    if (!formats.has(fmt)) formats.set(fmt, new Map())
    const files = formats.get(fmt)
    if (!files.has(row.file)) files.set(row.file, [])
    files.get(row.file).push(row)
  }
  return [...formats].map(([fmt, files]) => <details key={fmt} open>
    <summary>{fmt} · {files.size} files</summary>
    {[...files].map(([file, items]) => <details key={file} style={{ margin: '8px 0 8px 16px' }}>
      <summary>{file} · {items.reduce((n, row) => n + countOf(row), 0)} findings</summary>
      <ul>{items.map((row, index) => {
        const sc = scOf(row.criterion || row.rule_id || row.wcag)
        return <li key={row.id || index}><strong>SC {sc || 'not recorded'}{names[sc] ? ` — ${names[sc]}` : ''}</strong>
          {' · '}{countOf(row)} findings
          <p>{row.reason || row.detail || row.primary_reason?.replaceAll('_', ' ') || categoryLabel(row.category || remediationCategory(row))}</p>
          {row.severity && <small>Severity: {row.severity}</small>}
        </li>
      })}</ul>
    </details>)}
  </details>)
}

export default function RemediationCategoryBreakdown({ rows = [], title = 'Remediation categories', note }) {
  const [selected, setSelected] = useState(null)
  const grouped = REMEDIATION_CATEGORIES.map(([key, label]) => ({ key, label,
    rows: rows.filter(row => (row.category || remediationCategory(row)) === key) }))
  const active = grouped.find(group => group.key === selected)
  return <section aria-label={title}>
    <h3>{title}</h3>
    {note && <p className="muted">{note}</p>}
    <div role="group" aria-label="Remediation categories" style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      {grouped.map(group => <button key={group.key} type="button" aria-pressed={selected === group.key}
        disabled={!group.rows.length} onClick={() => setSelected(selected === group.key ? null : group.key)}>
        {group.label} · {group.rows.reduce((n, row) => n + countOf(row), 0)}
      </button>)}
    </div>
    {rows.length > 0 && <p className="remediation-category-total">{rows.reduce((n, row) => n + countOf(row), 0)} findings across remediation categories</p>}
    {active && <div role="region" aria-label={active.label}><h4>{active.label}</h4><FindingGroups rows={active.rows} /></div>}
  </section>
}

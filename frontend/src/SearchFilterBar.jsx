import { useState } from 'react'

// Shared search + facet-filter bar for every tab that renders a navigable file
// list (Discover, Remediate triage, Publish queue, segment drawers). One text
// query (filename substring) AND-ed with any number of facet groups; within a
// group selections are OR-ed ("PDF or DOCX"), across groups AND-ed ("PDF and
// critical"). Chips show live counts and facets with fewer than two distinct
// values hide themselves — a filter that can't change the list is noise.
//
// The state hook is separate from the bar so a parent can compute its filtered
// list wherever it already builds rows (including inside render IIFEs where
// hooks can't live) via the pure predicate from matchesFilters(ctl, …).

export function useSearchFilter() {
  const [query, setQuery] = useState('')
  const [sel, setSel] = useState({})              // { facetKey: Set(values) }
  const q = query.trim().toLowerCase()
  const active = q !== '' || Object.values(sel).some((s) => s.size > 0)
  const toggle = (key, v) => setSel((s) => {
    const n = { ...s, [key]: new Set(s[key] || []) }
    if (n[key].has(v)) n[key].delete(v); else n[key].add(v)
    return n
  })
  const clear = () => { setQuery(''); setSel({}) }
  return { query, setQuery, q, sel, toggle, clear, active }
}

// Predicate factory: text(item) is the searchable name; each facet is
// { key, label, get: (item) => value | value[] }.
export const matchesFilters = (ctl, facets, text) => (item) => {
  if (ctl.q && !text(item).toLowerCase().includes(ctl.q)) return false
  return facets.every((f) => {
    const s = ctl.sel[f.key]
    if (!s || !s.size) return true
    const v = f.get(item)
    const arr = Array.isArray(v) ? v : [v]
    return arr.some((x) => x != null && s.has(x))
  })
}

const MAX_OPTIONS = 7  // most-common values per facet — beyond this a chip row stops being scannable

export default function SearchFilterBar({ ctl, items = [], facets = [], text = (f) => f.file || '',
                                          placeholder = 'Search files by name…', noun = 'files' }) {
  const kept = items.filter(matchesFilters(ctl, facets, text)).length
  return (
    <div className="sfbar">
      <div className="sfrow">
        <input type="search" className="sfinput" value={ctl.query} placeholder={placeholder}
               aria-label={placeholder} onChange={(e) => ctl.setQuery(e.target.value)} />
        {ctl.active && (
          <span className="sfcount" role="status" aria-live="polite">
            <b>{kept.toLocaleString()}</b> of {items.length.toLocaleString()} {noun}
            <button className="ghost small" style={{ marginLeft: 8 }} onClick={ctl.clear}>✕ clear</button>
          </span>
        )}
      </div>
      {facets.map((f) => {
        // Live option list: distinct values with counts, respecting the query and
        // the OTHER facets (so counts answer "what would I get if I clicked this").
        const others = facets.filter((o) => o.key !== f.key)
        const base = items.filter(matchesFilters(ctl, others, text))
        const counts = {}
        base.forEach((it) => {
          const v = f.get(it)
          const arr = Array.isArray(v) ? v : [v]
          arr.forEach((x) => { if (x != null && x !== '') counts[x] = (counts[x] || 0) + 1 })
        })
        const selSet = ctl.sel[f.key] || new Set()
        // Keep selected values visible even when their count drops to 0.
        selSet.forEach((v) => { if (!(v in counts)) counts[v] = 0 })
        const opts = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, MAX_OPTIONS)
        if (opts.length < 2 && !selSet.size) return null
        return (
          <div className="sffacet" key={f.key} role="group" aria-label={`Filter by ${f.label}`}>
            <span className="sflabel">{f.label}</span>
            {opts.map(([v, n]) => (
              <button key={v} className={selSet.has(v) ? 'fchip on' : 'fchip'}
                      aria-pressed={selSet.has(v)} onClick={() => ctl.toggle(f.key, v)}>
                {String(v)} <span className="sfn">{n.toLocaleString()}</span>
              </button>
            ))}
          </div>
        )
      })}
    </div>
  )
}

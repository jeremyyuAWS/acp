import { useState, useMemo } from 'react'
import { OWNERS, SENIORITY_ORDER } from './sim.js'

const LS_KEY = 'mova_delegations'
const load = () => { try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}') } catch { return {} } }
const persist = (d) => localStorage.setItem(LS_KEY, JSON.stringify(d))

export const loadDelegations = load

// Admin panel — reassign all documents owned by a departed team member to another person.
// Stored in localStorage so the assignment survives page reloads within the demo session.
export default function OwnerDelegate({ files = [], onChanged }) {
  const [delegations, setDelegations] = useState(load)

  const ownerStats = useMemo(() => {
    const counts = {}
    files.forEach((f) => { const o = f.owner || '—'; counts[o] = (counts[o] || 0) + 1 })
    const rows = OWNERS.map((o) => ({ name: o.n, seniority: o.sr, count: counts[o.n] || 0, delegatedTo: delegations[o.n] || null }))
    rows.sort((a, b) => SENIORITY_ORDER.indexOf(a.seniority) - SENIORITY_ORDER.indexOf(b.seniority))
    return rows
  }, [files, delegations])

  const delegate = (from, to) => {
    const next = to
      ? { ...delegations, [from]: to }
      : (() => { const n = { ...delegations }; delete n[from]; return n })()
    setDelegations(next); persist(next); onChanged?.(next)
  }

  const totalDelegated = Object.keys(delegations).reduce((s, k) => s + (ownerStats.find((o) => o.name === k)?.count || 0), 0)

  return (
    <div>
      <p className="muted" style={{ marginBottom: 14 }}>
        Reassign documents when a team member departs — all their files are immediately attributed to the new owner across the estate.
        {totalDelegated > 0 && <b style={{ color: 'var(--ink)', marginLeft: 6 }}>{totalDelegated} file{totalDelegated !== 1 ? 's' : ''} currently delegated.</b>}
      </p>
      <table className="ruletable" style={{ width: '100%' }}>
        <thead>
          <tr>
            <th style={{ textAlign: 'left' }}>Owner</th>
            <th style={{ textAlign: 'left' }}>Seniority</th>
            <th style={{ textAlign: 'right', paddingRight: 16 }}>Files</th>
            <th style={{ textAlign: 'left' }}>Delegation</th>
          </tr>
        </thead>
        <tbody>
          {ownerStats.map((o) => (
            <tr key={o.name} style={o.delegatedTo ? { background: 'var(--surface2, #f8f8f8)' } : undefined}>
              <td style={{ fontWeight: o.delegatedTo ? 400 : 500, textDecoration: o.delegatedTo ? 'line-through' : 'none', color: o.delegatedTo ? 'var(--muted)' : 'inherit' }}>
                {o.name}
              </td>
              <td className="muted" style={{ fontSize: 12 }}>{o.seniority}</td>
              <td style={{ textAlign: 'right', paddingRight: 16, fontVariantNumeric: 'tabular-nums' }}>{o.count}</td>
              <td>
                {o.delegatedTo ? (
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span className="badge" style={{ background: 'var(--success-bg)', color: 'var(--success-fg)', fontWeight: 500 }}>→ {o.delegatedTo}</span>
                    <button className="ghost small" style={{ fontSize: 11 }} onClick={() => delegate(o.name, null)}>✕ undo</button>
                  </span>
                ) : (
                  <select
                    style={{ fontSize: 12 }}
                    value=""
                    onChange={(e) => { if (e.target.value) delegate(o.name, e.target.value) }}
                  >
                    <option value="">— Keep with {o.name}</option>
                    {OWNERS.filter((x) => x.n !== o.name).map((x) => (
                      <option key={x.n} value={x.n}>{x.n} ({x.sr})</option>
                    ))}
                  </select>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

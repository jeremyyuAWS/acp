import { useState, useMemo } from 'react'
import { SEV, sevOf, reasonOf, priorityScore, groupLabel } from './hitlMeta.js'

// Rules whose fix IS a value a human writes/edits (alt text, link text, title, label) —
// these get an editable "approved value" box (the AI draft, if any, prefilled). Judgement
// rules (contrast) have no value to type, just approve/reject.
const VALUE_FIX = new Set(['1.1.1', '2.4.4', '2.4.9', '2.4.2', '3.3.2'])
const scOf = (r) => String(r || '').replace(/^SC[_ ]?/i, '').replace(/_/g, '.').match(/^\d+\.\d+\.\d+/)?.[0] || ''
const isToday = (iso) => { if (!iso) return false; const d = new Date(iso), n = new Date(); return d.toDateString() === n.toDateString() }

// The full-screen "AI Work Inbox" — GitHub-PRs-meets-Gmail. Items are grouped by issue
// type, priority-sorted, each showing the REAL reason it escalated to a human, with
// one-click approve / reject / skip (and inline edit of the AI-drafted value).
export default function ReviewCenter({ items, onAct, onClose, onRefresh, error }) {
  const [expanded, setExpanded] = useState(null)
  const [edits, setEdits] = useState({})       // itemId -> edited approved value
  const [notes, setNotes] = useState({})       // itemId -> reviewer note
  const [busy, setBusy] = useState(null)        // itemId currently acting

  const pending = useMemo(() => items.filter((i) => i.status === 'pending'), [items])
  const resolvedToday = items.filter((i) => i.status !== 'pending' && isToday(i.reviewed_at))
  const approvedN = items.filter((i) => i.status === 'approved').length
  const rejectedN = items.filter((i) => i.status === 'rejected').length
  const acceptance = approvedN + rejectedN ? Math.round((approvedN / (approvedN + rejectedN)) * 100) : null
  const highN = pending.filter((i) => sevOf(i) === 'high').length

  // Group pending by issue type; order groups by their most-urgent item.
  const groups = useMemo(() => {
    const m = new Map()
    for (const it of pending) {
      const k = groupLabel(it)
      if (!m.has(k)) m.set(k, [])
      m.get(k).push(it)
    }
    return [...m.entries()]
      .map(([label, its]) => ({ label, items: its.sort((a, b) => priorityScore(b) - priorityScore(a)) }))
      .sort((a, b) => priorityScore(b.items[0]) - priorityScore(a.items[0]))
  }, [pending])

  const doAct = (it, status) => {
    setBusy(it.id)
    const val = VALUE_FIX.has(scOf(it.rule_id)) ? (edits[it.id] ?? it.approved_value ?? null) : null
    Promise.resolve(onAct(it.id, status, notes[it.id] || null, status === 'approved' ? val : null))
      .finally(() => { setBusy(null); setExpanded(null) })
  }

  const approveGroup = (grp) => grp.items.forEach((it) => {
    if (!VALUE_FIX.has(scOf(it.rule_id))) onAct(it.id, 'approved')   // bulk-approve only judgement items (no value needed)
  })

  return (
    <div className="rc-overlay" role="dialog" aria-modal="true" aria-label="Human review center">
      <div className="rc-panel">
        <div className="rc-head">
          <div>
            <h2 className="rc-title">🔔 AI Work Inbox</h2>
            <p className="muted rc-sub">AI-drafted and low-confidence fixes awaiting your approval before they can be certified.</p>
          </div>
          <button className="rc-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="rc-metrics">
          <div className="rc-metric"><span>Pending</span><b>{pending.length}</b></div>
          <div className="rc-metric"><span>High priority</span><b style={{ color: highN ? SEV.high.color : undefined }}>{highN}</b></div>
          <div className="rc-metric"><span>Resolved today</span><b>{resolvedToday.length}</b></div>
          <div className="rc-metric"><span>AI draft acceptance</span><b>{acceptance == null ? '—' : `${acceptance}%`}</b></div>
        </div>

        <div className="rc-body">
          {error && <div className="rc-empty">The review queue is unavailable right now. <button className="ghost small" onClick={onRefresh}>Retry</button></div>}
          {!error && pending.length === 0 && <div className="rc-empty">All caught up — nothing awaiting review. ✓</div>}

          {groups.map((grp) => (
            <section className="rc-group" key={grp.label}>
              <div className="rc-group-head">
                <span className="rc-group-title">{grp.label} <span className="muted">· {grp.items.length}</span></span>
                {grp.items.some((it) => !VALUE_FIX.has(scOf(it.rule_id))) && (
                  <button className="ghost small" onClick={() => approveGroup(grp)}>✓ Approve all judgement items</button>
                )}
              </div>
              {grp.items.map((it) => {
                const s = SEV[sevOf(it)] || SEV.medium
                const isVal = VALUE_FIX.has(scOf(it.rule_id))
                const isOpen = expanded === it.id
                return (
                  <div className={`rc-item${isOpen ? ' rc-item-open' : ''}`} key={it.id}>
                    <button className="rc-item-row" onClick={() => setExpanded(isOpen ? null : it.id)} aria-expanded={isOpen}>
                      <span className="rc-sevchip" style={{ background: s.bg, color: s.color }}>{s.label}</span>
                      <span className="rc-item-file">{it.file || 'document'}</span>
                      {it.finding_count > 1 && <span className="muted rc-item-count">{it.finding_count} findings</span>}
                      <span className="rc-item-reason">⚑ {reasonOf(it)}</span>
                      <span className="rc-item-caret" aria-hidden="true">{isOpen ? '▾' : '▸'}</span>
                    </button>
                    {isOpen && (
                      <div className="rc-item-detail">
                        <div className="rc-escalation">
                          <b>Escalated because</b>
                          <ul>
                            <li>{reasonOf(it)}</li>
                            <li>Deterministic fixes ran first and could not resolve this criterion.</li>
                            <li>Human approval is required before the document can be certified.</li>
                          </ul>
                        </div>
                        {isVal && (
                          <label className="rc-valedit">
                            <span className="muted">Approved value {it.approved_value ? '(AI draft — edit as needed)' : ''}</span>
                            <textarea
                              value={edits[it.id] ?? it.approved_value ?? ''}
                              placeholder="Type the value a screen reader should announce…"
                              onChange={(e) => setEdits((m) => ({ ...m, [it.id]: e.target.value }))} />
                          </label>
                        )}
                        <input className="rc-note" placeholder="Reviewer note (optional)"
                               value={notes[it.id] || ''}
                               onChange={(e) => setNotes((m) => ({ ...m, [it.id]: e.target.value }))} />
                        <div className="rc-actions">
                          <button className="rc-approve" disabled={busy === it.id} onClick={() => doAct(it, 'approved')}>✓ Approve</button>
                          <button className="ghost small" disabled={busy === it.id} onClick={() => doAct(it, 'rejected')}>✕ Reject</button>
                          <button className="ghost small" disabled={busy === it.id} onClick={() => doAct(it, 'skipped')}>⏭ Skip</button>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}

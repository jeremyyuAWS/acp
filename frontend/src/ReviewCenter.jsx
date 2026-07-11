import { useState, useMemo, useEffect } from 'react'
import { SEV, sevOf, reasonOf, priorityScore, groupLabel } from './hitlMeta.js'
import { confidenceForFinding, confClass } from './confidence.js'
import { openTraceUrl } from './api.js'
import EvidenceCard from './EvidenceCard.jsx'
// proposalMeta / firstProposed live in reviewCard.js — the single source of truth for how a
// hitl_queue.proposals row is read. EvidenceCard uses them too; don't fork the logic.
import { VALUE_FIX, firstProposed, proposalMeta } from './reviewCard.js'

// Rules whose fix IS a value a human writes/edits (alt text, link text, title, label) —
// these get an editable "approved value" box (the AI draft, if any, prefilled). Judgement
// rules (contrast) have no value to type, just approve/reject.
const scOf = (r) => String(r || '').replace(/^SC[_ ]?/i, '').replace(/_/g, '.').match(/^\d+\.\d+\.\d+/)?.[0] || ''
const isToday = (iso) => { if (!iso) return false; const d = new Date(iso), n = new Date(); return d.toDateString() === n.toDateString() }

// The full-screen "AI Work Inbox" — GitHub-PRs-meets-Gmail. Items are grouped by issue
// type, priority-sorted, each showing the REAL reason it escalated to a human, with
// one-click approve / reject / skip (and inline edit of the AI-drafted value).
export default function ReviewCenter({ items, onAct, onClose, onRefresh, error }) {
  const [expanded, setExpanded] = useState(null)
  const [busy, setBusy] = useState(null)        // itemId currently acting

  const pending = useMemo(() => items.filter((i) => i.status === 'pending'), [items])
  const resolvedToday = items.filter((i) => i.status !== 'pending' && isToday(i.reviewed_at))
  const approvedN = items.filter((i) => i.status === 'approved').length
  const rejectedN = items.filter((i) => i.status === 'rejected').length
  const acceptance = approvedN + rejectedN ? Math.round((approvedN / (approvedN + rejectedN)) * 100) : null
  const highN = pending.filter((i) => sevOf(i) === 'high').length
  const reviewedN = items.filter((i) => i.status !== 'pending').length
  const totalN = items.length

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

  // Flat render-order list + a cursor, for keyboard-driven review (j/k, a/r/s, Enter).
  const ordered = useMemo(() => groups.flatMap((g) => g.items), [groups])
  const [cursor, setCursor] = useState(0)

  // Bulk path only. A single item is decided inside its EvidenceCard, which carries the
  // reviewer's note, the (possibly edited) value, and the review telemetry.
  const doAct = (it, status) => {
    setBusy(it.id)
    // An item carrying an AI proposal takes a value even if its SC isn't in VALUE_FIX, and
    // the proposed value is what a bulk approve accepts (there is no per-item edit here).
    const takesValue = VALUE_FIX.has(scOf(it.rule_id)) || !!(it.proposals && it.proposals.length)
    const val = takesValue ? (firstProposed(it) ?? it.approved_value ?? null) : null
    Promise.resolve(onAct(it.id, status, null, status === 'approved' ? val : null))
      .catch(() => {})   // act() already reverts optimistic state on failure; avoid an unhandled rejection
      .finally(() => { setBusy(null); setExpanded(null) })
  }

  // Keyboard-driven review — power reviewers never touch the mouse. Typing in a note /
  // value box is never hijacked; Escape closes.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') { onClose(); return }
      const tag = (e.target?.tagName || '').toUpperCase()
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (!ordered.length) return
      const cur = ordered[Math.min(cursor, ordered.length - 1)]
      if (e.key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(ordered.length - 1, c + 1)) }
      else if (e.key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); setCursor((c) => Math.max(0, c - 1)) }
      else if (e.key === 'Enter') { e.preventDefault(); setExpanded((x) => (x === cur.id ? null : cur.id)) }
      else if (e.key === 'a') { e.preventDefault(); doAct(cur, 'approved') }
      else if (e.key === 'r') { e.preventDefault(); doAct(cur, 'rejected') }
      else if (e.key === 's') { e.preventDefault(); doAct(cur, 'skipped') }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [ordered, cursor, onClose])

  // A "judgement" item has no value to type (no VALUE_FIX rule and no AI proposal) — only
  // those are safe to bulk-approve; a proposal must be reviewed individually.
  const isJudgement = (it) => !VALUE_FIX.has(scOf(it.rule_id)) && !(it.proposals && it.proposals.length)
  const approveGroup = (grp) => grp.items.forEach((it) => { if (isJudgement(it)) onAct(it.id, 'approved') })

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
        <div className="rc-kbd-hint" aria-hidden="true">↑↓ / j k navigate · <b>a</b> approve · <b>r</b> I’ll fix it · <b>s</b> reject · Enter expand · Esc close</div>
        {totalN > 0 && (
          <div className="rc-progress">
            <span className="track"><i style={{ width: `${Math.round((reviewedN / totalN) * 100)}%` }} /></span>
            <span className="muted">{reviewedN} of {totalN} reviewed</span>
          </div>
        )}

        <div className="rc-body">
          {error && <div className="rc-empty">The review queue is unavailable right now. <button className="ghost small" onClick={onRefresh}>Retry</button></div>}
          {!error && pending.length === 0 && <div className="rc-empty">All caught up — nothing awaiting review. ✓</div>}

          {groups.map((grp) => (
            <section className="rc-group" key={grp.label}>
              <div className="rc-group-head">
                <span className="rc-group-title">{grp.label} <span className="muted">· {grp.items.length}</span></span>
                {grp.items.some((it) => isJudgement(it)) && (
                  <button className="ghost small" onClick={() => approveGroup(grp)}>✓ Approve all judgement items</button>
                )}
              </div>
              {grp.items.map((it) => {
                const s = SEV[sevOf(it)] || SEV.medium
                const isOpen = expanded === it.id
                // Confidence (confidence.js) — helps a reviewer triage. When the item carries
                // an AI proposal, the chip reflects it: a validated deterministic proposal is
                // a fast Medium confirm; a subjective (decorative / sensory) one is Low and
                // wants judgement. Otherwise it falls back to detection-method confidence.
                const conf = confidenceForFinding({ sc: scOf(it.rule_id), proposal: proposalMeta(it) })
                return (
                  <div className={`rc-item${isOpen ? ' rc-item-open' : ''}${ordered[cursor]?.id === it.id ? ' rc-item-cursor' : ''}`} key={it.id}>
                    <button className="rc-item-row" onClick={() => setExpanded(isOpen ? null : it.id)} aria-expanded={isOpen}>
                      {/* Two chips, two different things. A bare "Medium" beside a bare "High"
                          reads as a contradiction — say which is which. */}
                      <span className="rc-sevchip" style={{ background: s.bg, color: s.color }}
                            title={`WCAG severity of this criterion: ${s.label}`}>{s.label} severity</span>
                      <span className="rc-item-file">{it.file || 'document'}</span>
                      {it.finding_count > 1 && <span className="muted rc-item-count">{it.finding_count} findings</span>}
                      <span className="rc-item-reason">⚑ {reasonOf(it)}</span>
                      <span className={confClass(conf.level)} title={`Trust signal — how this was detected (tier: ${conf.level.label})`}>{conf.basis}</span>
                      <span className="rc-item-caret" aria-hidden="true">{isOpen ? '▾' : '▸'}</span>
                    </button>
                    {isOpen && (
                      <div className="rc-item-detail">
                        {/* The reviewer reviews the REMEDIATION, not a description of it:
                            thumbnail, the AI's proposed value, the evidence behind the
                            confidence level, and the real before/after diff for this
                            criterion. EvidenceCard owns the write so review telemetry
                            (edited / review_ms / ai_value) is recorded — that is how
                            "review in seconds" gets measured rather than asserted. */}
                        <EvidenceCard
                          item={it}
                          onAct={onAct}
                          onResolved={() => setExpanded(null)}
                          traceUrl={it.scan_id ? openTraceUrl(it.scan_id, 'file', it.file) : null}
                        />
                      </div>
                    )}
                  </div>
                )
              })}
            </section>
          ))}
          {pending.length > 0 && (
            <p className="muted rc-foot">↻ Re-validated against all engines after each approved fix — only re-passing files advance to publish.</p>
          )}
        </div>
      </div>
    </div>
  )
}

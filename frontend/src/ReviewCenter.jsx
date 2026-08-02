import { useState, useMemo, useEffect } from 'react'
import { SEV, sevOf, reasonOf } from './hitlMeta.js'
import { confidenceForFinding, confClass } from './confidence.js'
import { openTraceUrl } from './api.js'
import EvidenceCard from './EvidenceCard.jsx'
// proposalMeta / firstProposed live in reviewCard.js — the single source of truth for how a
// hitl_queue.proposals row is read. EvidenceCard uses them too; don't fork the logic.
import { VALUE_FIX, firstProposed, proposalMeta } from './reviewCard.js'
import RiskChip from './RiskChip.jsx'
import { reviewRisk, fmtEst } from './reviewRisk.js'
// Grouping lives in reviewGrouping.js so both modes produce ONE section shape and the
// by-document default is testable without mounting the screen.
import { buildSections, confirmableIn, loadGroupMode, saveGroupMode } from './reviewGrouping.js'
import DocIdentity from './DocIdentity.jsx'

// Rules whose fix IS a value a human writes/edits (alt text, link text, title, label) —
// these get an editable "approved value" box (the AI draft, if any, prefilled). Judgement
// rules (contrast) have no value to type, just approve/reject.
const scOf = (r) => String(r || '').replace(/^SC[_ ]?/i, '').replace(/_/g, '.').match(/^\d+\.\d+\.\d+/)?.[0] || ''
const isToday = (iso) => { if (!iso) return false; const d = new Date(iso), n = new Date(); return d.toDateString() === n.toDateString() }

// The full-screen "AI Work Inbox" — GitHub-PRs-meets-Gmail. Items are grouped by issue
// type, priority-sorted, each showing the REAL reason it escalated to a human, with
// one-click approve / reject / skip (and inline edit of the AI-drafted value).
export default function ReviewCenter({ items, onAct, onClose, onRefresh, error, docMeta = null }) {
  const [expanded, setExpanded] = useState(null)
  const [busy, setBusy] = useState(null)        // itemId currently acting
  const [sortMode, setSortMode] = useState('critical')   // 'critical' = triage | 'quick' = clear easy work first
  // By-document is the default because certification is per-document: clearing one file's items
  // is a finish line, and by-type work completes no document for an hour at a time. The choice
  // is read from localStorage on mount, so it survives a reload.
  const [groupMode, setGroupMode] = useState(loadGroupMode)
  const chooseGroupMode = (m) => { setGroupMode(m); saveGroupMode(m); setCursor(0) }

  const pending = useMemo(() => items.filter((i) => i.status === 'pending'), [items])
  const resolvedToday = items.filter((i) => i.status !== 'pending' && isToday(i.reviewed_at))
  const approvedN = items.filter((i) => i.status === 'approved').length
  const rejectedN = items.filter((i) => i.status === 'rejected').length
  const acceptance = approvedN + rejectedN ? Math.round((approvedN / (approvedN + rejectedN)) * 100) : null
  const highN = pending.filter((i) => sevOf(i) === 'high').length
  const reviewedN = items.filter((i) => i.status !== 'pending').length
  const totalN = items.length
  // Certification impact (#10): clearing this queue unblocks documents for certification, and the
  // estimated review effort tells the reviewer how far off "done" is — gamifies completion. Both
  // are real: the est is the sum of per-item risk-tier estimates; the doc count is the distinct
  // files these approvals clear. (The estate % projection needs the scan totals, which the inbox
  // doesn't hold — surfaced here as the document count instead, which is honest either way.)
  const estToClearS = pending.reduce((s, it) => s + reviewRisk(it).estSeconds, 0)
  const docsUnblocked = new Set(pending.map((i) => i.file || i.id)).size

  // Sections, in whichever grouping the reviewer chose. Both modes yield the same shape
  // ({ key, kind, head, count, groups }), so everything below renders one structure:
  //   document — one section per file, review types as its groups (the default; a finish line)
  //   type     — one section per review type, issue types as its groups (leverage across files)
  const sections = useMemo(
    () => buildSections(pending, { mode: groupMode, sortMode, docMeta }),
    [pending, sortMode, groupMode, docMeta])

  // Flat render-order list + a cursor, for keyboard-driven review (j/k, a/r/s, Enter).
  const ordered = useMemo(
    () => sections.flatMap((s) => s.groups.flatMap((g) => g.items)), [sections])
  const [cursor, setCursor] = useState(0)

  // Bulk path only. A single item is decided inside its EvidenceCard, which carries the
  // reviewer's note, the (possibly edited) value, and the review telemetry.
  const doAct = (it, status) => {
    setBusy(it.id)
    // An item carrying an AI proposal takes a value even if its SC isn't in VALUE_FIX, and
    // the proposed value is what a bulk approve accepts (there is no per-item edit here).
    const takesValue = VALUE_FIX.has(scOf(it.rule_id)) || !!(it.proposals && it.proposals.length)
    const val = takesValue ? (firstProposed(it) ?? it.approved_value ?? null) : null
    // Bulk/keyboard rejections carry reason 'unspecified' — recorded honestly as "no reason
    // asked", never dropped, so the feedback rollup separates them from chip-picked reasons.
    const opts = status === 'rejected' ? { rejectReason: 'unspecified' } : {}
    Promise.resolve(onAct(it.id, status, null, status === 'approved' ? val : null, opts))
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
  // Bulk "Confirm all" for the deterministic-confirmation tier (PRD HITL 2.0 bulk approval):
  // those items are ACP-applied rule-based fixes already re-validated, so a rubber-stamp of
  // them is the intended one-click — never offered for the proposal or authoring tiers, which
  // need per-item review.
  //
  // confirmableIn() is what keeps that true in BOTH groupings. A type section is one tier, so
  // sweeping the section and sweeping its confirmable items are the same set. A DOCUMENT
  // section holds every tier at once, so sweeping it wholesale would bulk-approve the AI
  // proposals and unwritten authoring work the by-type view deliberately refuses to offer a
  // bulk action for — the same button quietly meaning something different.
  const confirmSection = (sec) => confirmableIn(sec).forEach((it) => doAct(it, 'approved'))

  return (
    <div className="rc-overlay" role="dialog" aria-modal="true" aria-label="AI Work Inbox">
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
        {/* Labels must match the handler exactly: a→approved, r→rejected, s→skipped ("I'll fix
            it"). They were swapped — a reviewer pressing r expecting "I'll fix it" REJECTED. */}
        <div className="rc-kbd-hint" aria-hidden="true">↑↓ / j k navigate · <b>a</b> approve · <b>r</b> reject · <b>s</b> I’ll fix it · Enter expand · Esc close</div>
        {/* Grouping: the unit of delivery (a document) by default, or the unit of judgement
            (an issue type) for cross-file leverage. The choice persists across reloads. */}
        <div className="rc-groupmode" style={{ display: 'flex', gap: 6, alignItems: 'center', margin: '2px 0 6px', fontSize: 12 }}>
          <span className="muted">Group by:</span>
          <button className={`ghost small${groupMode === 'document' ? ' on' : ''}`} aria-pressed={groupMode === 'document'}
                  onClick={() => chooseGroupMode('document')}
                  title="One section per document — clear a file's items and it can be certified">📄 Document</button>
          <button className={`ghost small${groupMode === 'type' ? ' on' : ''}`} aria-pressed={groupMode === 'type'}
                  onClick={() => chooseGroupMode('type')}
                  title="One section per kind of work — decide the same pattern once across every file">🏷 Issue type</button>
          <span className="muted" style={{ marginLeft: 2 }}>
            {groupMode === 'document'
              ? 'certification is per-document — clearing one is a finish line'
              : 'the same judgement across many files is one decision'}
          </span>
        </div>
        {/* Risk-tier sort (#6): triage the criticals, or clear the quick wins first. */}
        <div className="rc-sort" style={{ display: 'flex', gap: 6, alignItems: 'center', margin: '2px 0 8px', fontSize: 12 }}>
          <span className="muted">Sort:</span>
          <button className={`ghost small${sortMode === 'critical' ? ' on' : ''}`} aria-pressed={sortMode === 'critical'}
                  onClick={() => setSortMode('critical')} title="Highest-risk findings first">Most critical</button>
          <button className={`ghost small${sortMode === 'quick' ? ' on' : ''}`} aria-pressed={sortMode === 'quick'}
                  onClick={() => setSortMode('quick')} title="Lowest estimated effort first — clear quick wins">Quickest first</button>
        </div>
        {totalN > 0 && (
          <div className="rc-progress">
            <span className="track"><i style={{ width: `${Math.round((reviewedN / totalN) * 100)}%` }} /></span>
            <span className="muted">{reviewedN} of {totalN} reviewed</span>
          </div>
        )}
        {/* Certification impact (#10): what clearing this queue achieves + how far off "done" is —
            real counts, honest estimate, gamifies completion. */}
        {pending.length > 0 && (
          <div className="rc-impact" style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap',
               margin: '2px 0 10px', padding: '8px 12px', borderRadius: 8, background: '#F4F8F0', border: '1px solid #CFE3BB' }}>
            <span style={{ fontWeight: 700, color: '#2C5209' }}>🎯 Approving these clears {docsUnblocked} document{docsUnblocked === 1 ? '' : 's'} for certification</span>
            <span className="muted">·</span>
            <span className="muted">about <b>{fmtEst(estToClearS)}</b> of review left ({pending.length} item{pending.length === 1 ? '' : 's'})</span>
          </div>
        )}

        <div className="rc-body">
          {error && <div className="rc-empty">The review queue is unavailable right now. <button className="ghost small" onClick={onRefresh}>Retry</button></div>}
          {!error && pending.length === 0 && <div className="rc-empty">All caught up — nothing awaiting review. ✓</div>}

          {sections.map((sec) => {
            const isDoc = sec.kind === 'document'
            // How many of this section's items are the rubber-stampable applied-fix tier. In
            // type mode that is the whole section; in document mode it is the confirm-tier
            // subset, and the button must say so rather than implying it clears the document.
            const bulkN = confirmableIn(sec).length
            return (
            <section className={`rc-type rc-sec-${sec.kind}`} key={sec.key}
                     aria-label={isDoc ? `Document ${sec.head.name}` : sec.head.label}>
              {/* The section header is the contract for everything under it. By document, that
                  is WHICH FILE the reviewer is about to change — filename, where it lives, and
                  how many items stand between it and certification. By type, it is what kind of
                  work this is and what clicking approve actually does. */}
              <div className={`rc-type-head ${isDoc ? 'rc-doc-head' : `rc-type-${sec.head.key}`}`}>
                {isDoc ? (
                  <>
                    <DocIdentity item={sec.groups[0].items[0]} meta={docMeta?.[sec.head.file]} size="head" showPage={false} />
                    <span className="muted rc-type-promise">
                      {sec.count} item{sec.count === 1 ? '' : 's'} between this document and certification
                    </span>
                  </>
                ) : (
                  <>
                    <span className="rc-type-title">{sec.head.icon} {sec.head.label} <b>· {sec.count}</b></span>
                    <span className="muted rc-type-promise">{sec.head.promise}</span>
                  </>
                )}
                {/* Bulk one-click only for the deterministic-confirmation tier: those fixes are
                    already applied + re-validated, so confirming them is a rubber-stamp. The
                    proposal + authoring tiers deliberately have no bulk action — which is why
                    this counts confirmable items, not section size. */}
                {bulkN > 1 && (
                  <button className="rc-type-bulk" onClick={() => confirmSection(sec)}
                          title={isDoc
                            ? `Confirm this document's ${bulkN} already-applied fixes. Its AI proposals and authoring items are not touched — those need per-item review.`
                            : 'Confirm every already-applied fix in this section'}>
                    ✓ Confirm {bulkN} applied fix{bulkN === 1 ? '' : 'es'}
                  </button>
                )}
              </div>
          {sec.groups.map((grp) => (
            <section className="rc-group" key={grp.label}>
              <div className="rc-group-head">
                {/* Inside a document, the groups ARE the review types, so each keeps its icon
                    and its promise: a drafted proposal and an already-applied fix are still
                    different jobs even when they sit under one filename. */}
                <span className="rc-group-title">
                  {grp.type ? `${grp.type.icon} ` : ''}{grp.label} <span className="muted">· {grp.items.length}</span>
                </span>
                {grp.type && <span className="muted rc-group-promise">{grp.type.promise}</span>}
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
                      <RiskChip item={it} compact />
                      {/* WHICH document — the question the card must answer before any other.
                          This was a minor secondary label; a reviewer approving a change has to
                          be able to tell at a glance which file they are changing, and
                          Clinical-FAQ-39.html vs -54.html is not a distinction a rule name makes. */}
                      <DocIdentity item={it} meta={docMeta?.[it.file]} />
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
            </section>
          )})}
          {pending.length > 0 && (
            <p className="muted rc-foot">↻ Re-validated against all engines after each approved fix — only re-passing files advance to publish.</p>
          )}
        </div>
      </div>
    </div>
  )
}

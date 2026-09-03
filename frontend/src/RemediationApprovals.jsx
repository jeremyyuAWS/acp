import { useState } from 'react'
import { approvalQueue, reconcileQueue } from './approvalQueue.js'

// R5 — the approval queue. Every AI-drafted fix, waiting for a person, showing what it would write.
//
// A REVIEWER WHO CANNOT SEE THE CHANGE CANNOT MEANINGFULLY APPROVE IT. So the draft itself is on
// the row, verbatim, in full — not a summary of it, not a count of how many there are, not the
// phrase "AI fix ready". Where the proposal named the passage it replaces, the before is on the row
// too, so the approval is a comparison rather than an act of faith.
//
// EDIT IS NOT A SECOND-CLASS PATH. The point of human review is that the human may disagree, and a
// queue where the cheap action is Approve and the expensive one is "open something else" produces
// approvals. Editing happens in place, on the row, and the edited text is what gets written —
// flagged as edited, because whether reviewers change what the model wrote is the only honest
// signal anyone has about how good the drafts are.
//
// WHAT THIS SCREEN REFUSES TO DO. It does not offer "approve all". Nothing here is applied without
// an explicit human action, and one press that accepts forty model-written values is that guarantee
// in name only. It also never renders an Approve button on a row with no draft: those rows exist,
// they arrive in the same list from the same endpoint, and they are authoring work rather than
// approvals — so they are shown separately, said plainly, and given no button.

const kicker = { fontSize: 11.5, letterSpacing: '.07em', textTransform: 'uppercase',
                 color: 'var(--muted)', fontWeight: 600 }
const mono = { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12 }
const rowStyle = { borderTop: '1px solid var(--line)', padding: '12px 0' }

function Location({ item }) {
  return (
    <span style={{ fontSize: 12.5 }}>
      <b>{item.sc}</b>{item.ruleName ? ` ${item.ruleName}` : ''}
      {' · '}<span style={mono}>{item.file}</span>
      {item.page != null && <span className="muted"> · page {item.page}</span>}
    </span>
  )
}

/**
 * @param items     hitl_queue rows from GET /hitl/queue?scan_id=…  — pass null while loading, and
 *                  the panel renders nothing rather than an empty queue
 * @param onApprove (id, value, {edited}) => void. `value` is null when the reviewer accepted the
 *                  draft as written — the backend reads null as "use the proposal's own value",
 *                  so this screen never re-sends text it did not change.
 * @param onReject  (id) => void. Optional: omit it and no Reject control renders.
 * @param busyId    the row currently being written, so its controls disable while it is in flight
 */
export default function RemediationApprovals({ items, onApprove, onReject, busyId = null }) {
  const [edits, setEdits] = useState({})       // id → the reviewer's text, while they are editing

  const q = approvalQueue(items)
  // Nothing, rather than "0 drafts awaiting your approval". An absent queue is not an empty one.
  if (!q) return null
  const r = reconcileQueue(q)

  const startEdit = (item) => setEdits((e) => ({ ...e, [item.id]: item.draft ?? '' }))
  const cancelEdit = (id) => setEdits((e) => { const n = { ...e }; delete n[id]; return n })
  const approve = (item) => {
    const edited = Object.prototype.hasOwnProperty.call(edits, item.id)
    const value = edited ? edits[item.id] : null
    onApprove?.(item.id, edited && value !== item.draft ? value : null,
                { edited: edited && value !== item.draft })
    cancelEdit(item.id)
  }

  return (
    <section className="panel remediationapprovals">
      <div style={kicker}>Drafts awaiting your approval · {q.awaiting.length}</div>

      {q.awaiting.length === 0 && (
        <p className="muted" style={{ fontSize: 12.5, margin: '10px 0 0', lineHeight: 1.6 }}>
          No draft is waiting for a decision.
        </p>
      )}

      {q.awaiting.map((item) => {
        const editing = Object.prototype.hasOwnProperty.call(edits, item.id)
        const busy = busyId === item.id
        return (
          <div key={item.id} style={rowStyle}>
            <Location item={item} />

            {item.before && (
              <div className="muted" style={{ ...mono, marginTop: 6, fontSize: 11.5, lineHeight: 1.6 }}>
                now: {item.before}
              </div>
            )}

            {/* The draft, verbatim. This is the thing being approved. */}
            {editing ? (
              <textarea
                aria-label={`Edit the draft for ${item.sc} in ${item.file}`}
                value={edits[item.id]}
                onChange={(e) => setEdits((s) => ({ ...s, [item.id]: e.target.value }))}
                rows={3}
                style={{ ...mono, width: '100%', marginTop: 6, padding: '7px 9px',
                         border: '1px solid var(--line)', borderRadius: 8, lineHeight: 1.6 }}
              />
            ) : (
              <div style={{ ...mono, marginTop: 6, padding: '7px 9px', borderRadius: 8,
                            background: '#EDF5EA', color: 'var(--success-fg-strong)', lineHeight: 1.6 }}>
                {item.draft}
              </div>
            )}

            {item.rationale && (
              <div className="muted" style={{ fontSize: 11.5, marginTop: 5, lineHeight: 1.6 }}>
                Why: {item.rationale}
              </div>
            )}

            {/* One press, N values. Said before the press, not discovered after it. */}
            {item.draftCount > 1 && (
              <div className="muted" style={{ fontSize: 11.5, marginTop: 5, lineHeight: 1.6 }}>
                This row carries {item.draftCount} drafts for {item.sc} in this document. Approving
                accepts all {item.draftCount}; only the first is shown above.
              </div>
            )}

            <div style={{ display: 'flex', gap: 7, marginTop: 9, alignItems: 'center' }}>
              <button className="small" type="button" disabled={busy} onClick={() => approve(item)}>
                {editing ? 'Approve my wording' : 'Approve'}
              </button>
              {editing ? (
                <button className="ghost small" type="button" disabled={busy}
                        onClick={() => cancelEdit(item.id)}>Cancel</button>
              ) : (
                <button className="ghost small" type="button" disabled={busy}
                        onClick={() => startEdit(item)}>Edit</button>
              )}
              {onReject && (
                <button className="ghost small" type="button" disabled={busy}
                        onClick={() => onReject(item.id)}>Reject</button>
              )}
              {busy && <span className="muted" style={{ fontSize: 11.5 }}>writing…</span>}
            </div>
          </div>
        )
      })}

      {/* ── The rows that look like approvals and are not ──────────────────────────────────── */}
      {q.undrafted.length > 0 && (
        <div style={{ marginTop: 14, paddingTop: 10, borderTop: '1px solid var(--line)' }}>
          <div style={{ fontSize: 13, fontWeight: 650 }}>
            {q.undrafted.length} finding{q.undrafted.length === 1 ? '' : 's'} in this queue with no
            draft
          </div>
          <p className="muted" style={{ fontSize: 12, margin: '5px 0 7px', lineHeight: 1.6 }}>
            Nothing was generated for these, so there is nothing to approve. They are authoring
            work: a person writes the fix.
          </p>
          <ul className="muted" style={{ fontSize: 12, margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
            {q.undrafted.map((item) => (
              <li key={item.id}><Location item={item} /></li>
            ))}
          </ul>
        </div>
      )}

      {/* ── The rule, where the buttons are ─────────────────────────────────────────────────── */}
      <p className="muted" style={{ fontSize: 12, marginTop: 12, paddingTop: 10,
                                    borderTop: '1px solid var(--line)', lineHeight: 1.6 }}>
        <b style={{ color: 'var(--ink)' }}>A draft is never applied without an explicit
        approval</b>, and there is no bulk approve. This is why drafted fixes are counted under
        human review and never under automatic — an AI draft is advice, not automation.
      </p>
      <div className="muted" style={{ fontSize: 12, marginTop: 6, lineHeight: 1.6 }}>
        {r.ok ? r.line
              : <b style={{ color: '#B3261E' }}>{r.line} — these do not add up ({r.sum}); this
                  screen has a bug and its counts should not be relied on.</b>}
      </div>
    </section>
  )
}

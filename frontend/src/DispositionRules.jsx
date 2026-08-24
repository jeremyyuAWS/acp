import { useState, useEffect, useCallback } from 'react'
import { confirm } from './ConfirmDialog.jsx'
import {
  listDispositionPolicies, createDispositionPolicy, setDispositionPolicyEnabled, previewDispositionPolicy,
  updateDispositionPolicy, previewDispositionDraft, deleteDispositionPolicy, reorderDispositionPolicies,
  listDispositionConflicts,
} from './api.js'
import {
  ACTIONS, CONDITIONS, LIFECYCLE_ACTIONS, actionSpec, draftProblem, draftToMatch, emptyDraft,
  matchCountText, matchProblem, matchToDraftValues, refusalText, ruleSentenceParts,
} from './lifecycleRules.js'

// Discover, step 2 — "Lifecycle rules" (design board DiscoverRules.dc.html).
//
// WHAT A RULE HERE ACTUALLY DOES, because the whole screen turns on it: at discovery time
// api/handlers._evaluate_discover_lifecycle_rules evaluates every ENABLED rule against the
// freshly inventoried files and, on a match, sets lifecycle_status to "Archive Candidate" or
// "Delete Candidate" and writes one audit row. That is all. No file is moved, trashed, renamed,
// downloaded or opened. Assess then excludes candidates by default, and a human resolves them.
//
// So this screen must never say a file was archived or deleted. It says tagged for review,
// recommendation, candidate, needs your decision — see lifecycleRules.js, which owns the wording.
// This is the one screen where a person writes a rule that SOUNDS destructive and is not, and the
// only thing standing between those two readings is the copy at the point the choice is made.
//
// SAFETY, mirrored from the backend rather than asserted:
//   * A new rule is created DISABLED (api.js createDispositionPolicy defaults enabled=0) and
//     approval-gated (requires_approval=true), so adding one changes nothing until it is enabled.
//   * "Delete" is Drive TRASH, recoverable — disposition.execute_action has no permanent-delete
//     path at all. Said in the ACTION control's own help text, not in a footnote.
//   * Create and enable are both owner-gated server-side (_require_admin). A non-admin's attempt
//     is refused with a 403; that refusal is surfaced inline next to the control, because a rule
//     that silently failed to save is indistinguishable from one that exists.
//   * Archive beats delete when both match (PRD §6, and the `else` branch of the delete/archive
//     precedence block in handlers.py): the reversible outcome is kept and the file is flagged.
//     Rules made here never set the delete-override config, so that default always holds for them.
//
// Lifecycle rules #4 — the draft's match count is live, fetched from POST /disposition/preview
// (api/routes/disposition.py's preview_draft) as the conditions are typed, before the rule is
// saved — see NewRule below. The saved-policy preview (POST /policies/{id}/preview) and this one
// share ONE evaluator server-side (`_preview`), so the count shown while typing is the count the
// saved rule will produce, not a separate estimate that could drift from it.
//
// Lifecycle rules #2 — a saved rule can be edited in place (RuleRow's "Edit"), not only
// duplicated or deleted. PUT /disposition/policies/{id} (`update_policy`) refuses to change a
// rule's match/action/action_config once it has recorded ANY history — files it already flagged
// carry its decision, and no record says which DEFINITION of the rule produced it, so an in-place
// edit would silently change what those records mean. That 409 is surfaced the same way every
// other refusal on this screen is; the route's own docstring is the fuller explanation of why
// versioning (build-plan item #10) is the real fix and deliberately not this one's job.

// Enabling a rule that would match at least this share of the tenant's estate gets an extra
// warning line in the confirm dialog on top of the count. A stated line, not a backend limit —
// it never blocks enabling, only makes an unusually broad rule harder to enable by accident.
const BROAD_RULE_PCT = 50

const line = '1px solid var(--line)'
const inp = {
  padding: '7px 10px', border: line, borderRadius: 8, background: 'var(--surface)',
  color: 'inherit', font: 'inherit', fontSize: 13, minWidth: 0, width: '100%',
}
const fieldLabel = {
  fontSize: 11.5, fontWeight: 600, letterSpacing: '.03em', color: 'var(--muted)', textTransform: 'uppercase',
}
const sentenceBox = {
  marginTop: 10, padding: '9px 12px', borderRadius: 8, fontSize: 12.5, lineHeight: 1.55,
  background: 'color-mix(in srgb, var(--plum) 6%, transparent)',
  border: '1px solid color-mix(in srgb, var(--plum) 18%, transparent)',
}
const alertStyle = { fontSize: 12.5, color: '#A32D2D', margin: '8px 0 0', lineHeight: 1.5 }

const MAX_PREVIEW_INLINE = 25

/** Inline table of files that matched a rule preview. */
function PreviewPanel({ docs, enabled, fetchedAt, onRefresh, busy, breakdown }) {
  const shown = docs.slice(0, MAX_PREVIEW_INLINE)
  const extra = docs.length - shown.length
  const COLS = ['Name', 'Location', 'Owner', 'Modified', 'Type', 'Size']
  const hasSuppressions = breakdown && (breakdown.superseded > 0 || breakdown.exempted > 0)
  const hasUnable = breakdown && breakdown.unable_to_evaluate > 0
  return (
    <div style={{ marginTop: 10, border: line, borderRadius: 9, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', flexWrap: 'wrap',
                    background: 'color-mix(in srgb, var(--plum) 4%, transparent)',
                    borderBottom: hasSuppressions || hasUnable || docs.length ? line : 'none' }}>
        <span style={{ fontSize: 12, fontWeight: 600 }}>
          {enabled
            ? `${docs.length} file${docs.length === 1 ? '' : 's'} matched`
            : `Hypothetical preview — ${docs.length} file${docs.length === 1 ? '' : 's'} would match if enabled`}
        </span>
        {fetchedAt && (
          <span className="muted" style={{ fontSize: 11 }}>
            as of {fetchedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
        <button className="ghost small" onClick={onRefresh} disabled={busy}
                style={{ marginLeft: 'auto' }}>
          {busy ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      {hasSuppressions && (
        <div style={{ display: 'flex', gap: 14, padding: '5px 12px', flexWrap: 'wrap',
                      borderBottom: docs.length ? line : 'none',
                      background: 'color-mix(in srgb, var(--plum) 2%, transparent)' }}>
          <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>
            <b style={{ color: 'inherit' }}>{breakdown.effective}</b> will receive the action
          </span>
          {breakdown.superseded > 0 && (
            <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>
              <b style={{ color: 'inherit' }}>{breakdown.superseded}</b> overridden by another rule
            </span>
          )}
          {breakdown.exempted > 0 && (
            <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>
              <b style={{ color: 'inherit' }}>{breakdown.exempted}</b> exempted (held)
            </span>
          )}
        </div>
      )}
      {hasUnable && (
        <div style={{ padding: '5px 12px', borderBottom: docs.length ? line : 'none',
                      background: 'color-mix(in srgb, var(--plum) 2%, transparent)' }}>
          <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>
            + <b style={{ color: 'inherit' }}>{breakdown.unable_to_evaluate}</b>{' '}
            file{breakdown.unable_to_evaluate === 1 ? '' : 's'} couldn't be evaluated —
            a required metadata field wasn't recorded, so they may or may not match
          </span>
        </div>
      )}
      {docs.length === 0 ? (
        <p className="muted" style={{ fontSize: 12.5, padding: '10px 12px', margin: 0 }}>
          No files currently match this rule.
        </p>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr>
                {COLS.map((h) => (
                  <th key={h} style={{ textAlign: 'left', padding: '6px 10px', fontWeight: 600,
                                       fontSize: 11, letterSpacing: '.03em', color: 'var(--muted)',
                                       borderBottom: line, textTransform: 'uppercase',
                                       background: 'var(--surface)' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((doc, i) => {
                const path = doc.path || doc.doc_id || '—'
                const name = path.split('/').filter(Boolean).pop() || path
                const folder = path.includes('/') ? path.substring(0, path.lastIndexOf('/')) || '/' : '—'
                const modDate = (doc.source_modified || '').substring(0, 10) || '—'
                const sz = doc.size_kb != null ? `${doc.size_kb} KB` : '—'
                return (
                  <tr key={doc.doc_id || i}
                      style={{ borderBottom: i < shown.length - 1 ? line : 'none' }}>
                    <td style={{ padding: '7px 10px', fontWeight: 500, whiteSpace: 'nowrap' }}>{name}</td>
                    <td style={{ padding: '7px 10px', color: 'var(--muted)', maxWidth: 200, overflow: 'hidden',
                                 textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{folder}</td>
                    <td style={{ padding: '7px 10px', color: 'var(--muted)', whiteSpace: 'nowrap' }}>{doc.owner || '—'}</td>
                    <td style={{ padding: '7px 10px', color: 'var(--muted)', whiteSpace: 'nowrap' }}>{modDate}</td>
                    <td style={{ padding: '7px 10px', color: 'var(--muted)', whiteSpace: 'nowrap' }}>{doc.doc_class || '—'}</td>
                    <td style={{ padding: '7px 10px', color: 'var(--muted)', whiteSpace: 'nowrap' }}>{sz}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {extra > 0 && (
            <p className="muted" style={{ fontSize: 11.5, padding: '6px 12px', margin: 0 }}>
              + {extra} more not shown
            </p>
          )}
        </div>
      )}
    </div>
  )
}

/** The rule as a sentence, with the parts a reader scans for in bold, plus the match count. */
function RuleSentence({ match, action, count, countOverride }) {
  return (
    <div style={sentenceBox} className="lifecycle-sentence">
      {ruleSentenceParts(match, action).map((p, i) => (p.b ? <b key={i}>{p.t}</b> : <span key={i}>{p.t}</span>))}{' '}
      <span className="muted" style={{ fontSize: 12 }}>{countOverride ?? matchCountText(count)}</span>
    </div>
  )
}

function ActionTag({ action }) {
  const spec = actionSpec(action)
  const tone = spec.action === 'delete' ? ['#FBE9E9', '#E5C4C4', '#A32D2D'] : ['#EEF2FB', '#D3DDF1', '#2B4A7E']
  return (
    <span className="lifecycle-tag" style={{ fontSize: 11, fontWeight: 600, padding: '2px 9px', borderRadius: 20,
                                             background: tone[0], border: `1px solid ${tone[1]}`, color: tone[2] }}>
      {spec.tag}
    </span>
  )
}

/** The name/action/conditions field grid — shared by the create form (NewRule) and a saved rule's
 *  edit form (RuleRow, lifecycle rules #2), so there is one field layout to keep in sync with
 *  CONDITIONS rather than two. `labelFor` lets each caller give its inputs distinct aria-labels —
 *  identity for NewRule (preserving its existing labels exactly), a per-rule suffix for an edit
 *  form, since a rule's own name/action/condition inputs would otherwise collide with every other
 *  rule's edit form and with NewRule's, all mounted on the same screen at once. */
function RuleFields({ draft, setDraft, labelFor }) {
  const setValue = (key, v) => setDraft((d) => ({ ...d, values: { ...d.values, [key]: v } }))
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
      <label style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        <span style={fieldLabel}>Name</span>
        <input style={inp} type="text" value={draft.name} aria-label={labelFor('Rule name')}
               placeholder="e.g. Finance retention"
               onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
      </label>
      <label style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        <span style={fieldLabel}>Action</span>
        <select style={inp} value={draft.action} aria-label={labelFor('Action')}
                onChange={(e) => setDraft((d) => ({ ...d, action: e.target.value }))}>
          {ACTIONS.map((a) => <option key={a.action} value={a.action}>{a.label}</option>)}
        </select>
      </label>
      {CONDITIONS.map((c) => (
        <label key={c.key} style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          <span style={fieldLabel}>{c.label}{c.unit ? ` (${c.unit})` : ''}</span>
          <input style={inp} aria-label={labelFor(c.label)} placeholder={c.placeholder}
                 type={c.kind === 'date' ? 'date' : 'text'}
                 inputMode={c.kind === 'number' ? 'numeric' : undefined}
                 value={draft.values[c.key]} onChange={(e) => setValue(c.key, e.target.value)} />
        </label>
      ))}
    </div>
  )
}

function RuleRow({ p, count, onCount, onChanged, onDuplicate, onMove, isFirst, isLast, rank }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const enabled = !!p.enabled
  // Preview expansion — docs stored locally; parent only needs the count.
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewDocs, setPreviewDocs] = useState(null)
  const [previewFetchedAt, setPreviewFetchedAt] = useState(null)
  const [previewBreakdown, setPreviewBreakdown] = useState(null)
  // Lifecycle rules #2 — edit a saved rule in place. The backend (PUT /disposition/policies/{id})
  // refuses to change match/action/action_config once a rule has recorded ANY history (409) —
  // name/requires_approval stay editable regardless — so this never tries to predict that
  // client-side; the refusal reaches the person the same way every other write on this screen
  // does, via `err`.
  const [editing, setEditing] = useState(false)
  const [editDraft, setEditDraft] = useState(null)
  const [editBusy, setEditBusy] = useState(false)
  const [editErr, setEditErr] = useState('')
  const startEdit = () => {
    setEditDraft({ name: p.name, action: p.action, values: matchToDraftValues(p.match) })
    setEditErr('')
    setEditing(true)
  }
  const cancelEdit = () => { setEditing(false); setEditDraft(null); setEditErr('') }
  const saveEdit = () => {
    const problem = draftProblem(editDraft)
    if (problem) { setEditErr(problem); return }
    // Enabling asks before it starts tagging (toggle, below); an edit to an ALREADY-enabled rule
    // takes effect just as immediately, so it earns the same "you are about to change what's
    // live" confirmation rather than saving silently.
    const doSave = () => {
      setEditBusy(true); setEditErr('')
      Promise.resolve(updateDispositionPolicy(p.policy_id, {
        name: editDraft.name.trim(), match: draftToMatch(editDraft), action: editDraft.action,
      }))
        .then(() => { setEditing(false); setEditDraft(null); onChanged() })
        .catch((e) => setEditErr(refusalText(e)))
        .finally(() => setEditBusy(false))
    }
    if (enabled) {
      confirm({
        title: `Save changes to "${editDraft.name.trim()}"?`,
        message: 'It is enabled, so the new conditions apply starting with your next Discover run. Files already tagged under the old conditions keep their status until then.',
        variant: 'warning', confirmLabel: 'Save',
      }).then((ok) => { if (ok) doSave() })
      return
    }
    doSave()
  }

  const doSetEnabled = (next) => {
    setBusy(true); setErr('')
    Promise.resolve(setDispositionPolicyEnabled(p.policy_id, next))
      .then(() => onChanged())
      .catch((e) => setErr(refusalText(e)))
      .finally(() => setBusy(false))
  }
  // Disabling warns that existing tags persist — files already tagged keep their lifecycle status
  // until the next Discover run re-evaluates them. Enabling previews first and asks, naming the
  // count and the share of the estate a person is committing to — not just "are you sure?".
  const toggle = () => {
    if (enabled) {
      confirm({
        title: `Disable "${p.name}"?`,
        message: 'It will stop tagging files in future Discover runs. Files already tagged by this rule keep their lifecycle status until the next run re-evaluates them.',
        variant: 'default', confirmLabel: 'Disable',
      }).then((ok) => { if (ok) doSetEnabled(false) })
      return
    }
    setBusy(true); setErr('')
    Promise.resolve(previewDispositionPolicy(p.policy_id))
      .then((r) => {
        const n = r?.would_match ?? null
        const total = r?.total ?? null
        onCount(p.policy_id, n)
        setBusy(false)
        if (n == null) {
          confirm({
            title: `Enable "${p.name}"?`,
            message: 'It will start tagging matching files immediately. (Could not check how many files it would match.)',
            variant: 'default', confirmLabel: 'Enable',
          }).then((ok) => { if (ok) doSetEnabled(true) })
          return
        }
        const pct = total ? Math.round((n / total) * 100) : null
        const outcome = actionSpec(p.action).outcome
        const msg = `This will ${n === 0 ? 'currently tag no files' : `tag ${n} file${n === 1 ? '' : 's'}${pct != null ? ` (${pct}% of your estate)` : ''} as ${outcome}`}, and any future match, until you disable it.`
        // BROAD_RULE_PCT: an arbitrary but stated line, not a backend limit — half the estate is
        // the point past which "this folder" usually stops being what a rule author meant.
        const broad = pct != null && pct >= BROAD_RULE_PCT
        confirm({
          title: `Enable "${p.name}"?`,
          message: msg,
          warning: broad ? `⚠ That's ${pct}% of your estate — check the conditions are as narrow as you intended before enabling.` : undefined,
          variant: broad ? 'warning' : 'default',
          confirmLabel: 'Enable',
        }).then((ok) => { if (ok) doSetEnabled(true) })
      })
      .catch((e) => {
        setBusy(false)
        confirm({
          title: `Enable "${p.name}"?`,
          message: `Could not check how many files it would match: ${refusalText(e)}`,
          variant: 'default', confirmLabel: 'Enable anyway',
        }).then((ok) => { if (ok) doSetEnabled(true) })
      })
  }
  const runPreview = () => {
    setBusy(true); setErr('')
    Promise.resolve(previewDispositionPolicy(p.policy_id))
      // `?? null` and not `?? 0`: a response without a count is an unanswered question, and
      // rendering it as zero would be the measured-zero lie this screen exists to avoid.
      .then((r) => {
        onCount(p.policy_id, r?.would_match ?? null)
        setPreviewDocs(r?.documents ?? [])
        setPreviewBreakdown(r?.effective != null ? {
          effective: r.effective,
          superseded: r.superseded ?? 0,
          exempted: r.exempted ?? 0,
          unable_to_evaluate: r.unable_to_evaluate ?? 0,
        } : null)
        setPreviewFetchedAt(new Date())
        setPreviewOpen(true)
      })
      .catch((e) => setErr(refusalText(e)))
      .finally(() => setBusy(false))
  }
  const previewBtnLabel = previewOpen
    ? 'Hide matches'
    : count != null
      ? `Show ${count} match${count === 1 ? '' : 'es'}`
      : 'Preview matches'
  // Only a rule with zero disposition_audit history can be deleted (mirrors the backend's
  // edit-after-history guard) — the route 409s and refusalText surfaces its message rather than
  // this button trying to predict history client-side and getting it wrong.
  const remove = () => {
    confirm({
      title: `Delete "${p.name}"?`,
      message: "This can't be undone.",
      variant: 'danger', confirmLabel: 'Delete',
    }).then((ok) => {
      if (!ok) return
      setBusy(true); setErr('')
      Promise.resolve(deleteDispositionPolicy(p.policy_id))
        .then(() => onChanged())
        .catch((e) => setErr(refusalText(e)))
        .finally(() => setBusy(false))
    })
  }
  const duplicate = () => {
    setBusy(true); setErr('')
    Promise.resolve(onDuplicate(p))
      .catch((e) => setErr(refusalText(e)))
      .finally(() => setBusy(false))
  }
  const move = (dir) => {
    setBusy(true); setErr('')
    Promise.resolve(onMove(p.policy_id, dir))
      .catch((e) => setErr(refusalText(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div className="lifecycle-rule" style={{ border: line, borderRadius: 11, padding: '13px 15px', marginBottom: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        {/* Priority order, not decoration: two files matched by both an archive and a delete
            rule settle on whichever rule is FIRST here (disposition.resolve_candidate) — moving
            a rule up the list is moving it up the precedence a real conflict resolves by. */}
        <span style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          <button className="ghost small" onClick={() => move('up')} disabled={busy || isFirst}
                  aria-label={`Move rule ${p.name} up`} style={{ padding: '0 6px', lineHeight: 1.2 }}>▲</button>
          <button className="ghost small" onClick={() => move('down')} disabled={busy || isLast}
                  aria-label={`Move rule ${p.name} down`} style={{ padding: '0 6px', lineHeight: 1.2 }}>▼</button>
        </span>
        <span className="muted" style={{ fontSize: 11, width: 16, textAlign: 'center' }}>{rank}</span>
        <input type="checkbox" checked={enabled} onChange={toggle} disabled={busy}
               aria-label={`Enable rule ${p.name}`} style={{ width: 15, height: 15 }} />
        <span style={{ fontSize: 13.5, fontWeight: 600 }}>{p.name}</span>
        <ActionTag action={p.action} />
        <span className="muted" style={{ fontSize: 12 }}>{enabled ? 'Enabled' : 'Disabled — tags nothing yet'}</span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button className="ghost small"
                  onClick={previewOpen ? () => setPreviewOpen(false) : runPreview}
                  disabled={busy || editing}
                  aria-expanded={previewOpen}>
            {previewBtnLabel}
          </button>
          <button className="ghost small" onClick={startEdit} disabled={busy || editing}
                  aria-label={`Edit rule ${p.name}`}>Edit</button>
          <button className="ghost small" onClick={duplicate} disabled={busy || editing}>Duplicate</button>
          <button className="ghost small" onClick={remove} disabled={busy || editing}
                  aria-label={`Delete rule ${p.name}`}>Delete</button>
        </span>
      </div>
      {editing ? (
        <div style={{ marginTop: 10 }}>
          <RuleFields draft={editDraft} setDraft={setEditDraft}
                      labelFor={(l) => `${l} (editing ${p.name})`} />
          <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center' }}>
            <button className="small" onClick={saveEdit} disabled={editBusy}
                    aria-label={`Save changes to ${p.name}`}>{editBusy ? 'Saving…' : 'Save changes'}</button>
            <button className="ghost small" onClick={cancelEdit} disabled={editBusy}
                    aria-label={`Cancel editing ${p.name}`}>Cancel</button>
          </div>
          {editErr && <p style={alertStyle} role="alert">⚠ {editErr}</p>}
        </div>
      ) : (
        <>
          <RuleSentence match={p.match} action={p.action} count={count} />
          {previewOpen && previewDocs != null && (
            <PreviewPanel docs={previewDocs} enabled={enabled}
                          fetchedAt={previewFetchedAt}
                          onRefresh={runPreview} busy={busy}
                          breakdown={previewBreakdown} />
          )}
        </>
      )}
      {err && <p style={alertStyle} role="alert">⚠ {err}</p>}
    </div>
  )
}

function NewRule({ onCreated }) {
  const [draft, setDraft] = useState(emptyDraft)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [added, setAdded] = useState('')
  const spec = actionSpec(draft.action)
  const match = draftToMatch(draft)
  const problem = draftProblem(draft)
  // matchProblem, not draftProblem: previewing a draft depends only on its CONDITIONS, not its
  // name — gating it on the full submission check would mean a person filling in conditions
  // first, name last, sees no count until the very last field.
  const matchProb = matchProblem(draft)

  // Lifecycle rules #4 — preview a rule BEFORE it is saved, not only after (previewDispositionPolicy
  // needs a saved policy_id). Debounced so a person typing a folder path doesn't fire one request
  // per keystroke; the last edit within the window is the one that gets asked. Whole-estate, same
  // evaluator as the saved-rule preview (api/routes/disposition.py's shared `_preview`), so the
  // count shown while typing can't drift from what the saved rule will produce.
  const matchKey = JSON.stringify(match)
  const [previewCount, setPreviewCount] = useState(null)
  const [previewBusy, setPreviewBusy] = useState(false)
  const [previewErr, setPreviewErr] = useState(false)
  useEffect(() => {
    setPreviewCount(null); setPreviewErr(false)
    if (matchProb) return undefined   // no valid predicate yet — nothing to ask about
    let live = true
    setPreviewBusy(true)
    const t = setTimeout(() => {
      Promise.resolve(previewDispositionDraft(match, draft.action))
        .then((r) => { if (live) setPreviewCount(r?.would_match ?? null) })
        .catch(() => { if (live) setPreviewErr(true) })
        .finally(() => { if (live) setPreviewBusy(false) })
    }, 400)
    return () => { live = false; clearTimeout(t); setPreviewBusy(false) }
  }, [matchKey, draft.action, matchProb]) // eslint-disable-line react-hooks/exhaustive-deps

  const add = () => {
    if (problem) { setErr(problem); return }
    setBusy(true); setErr(''); setAdded('')
    Promise.resolve(createDispositionPolicy(draft.name.trim(), match, draft.action))
      .then((created) => {
        setAdded(draft.name.trim())
        setDraft(emptyDraft())
        // The created rule's id, when the API hands one back, so its real match count can be
        // fetched while it is still disabled.
        onCreated(created && created.policy_id ? created.policy_id : null)
      })
      .catch((e) => setErr(refusalText(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div className="lifecycle-new" style={{ border: '1px dashed color-mix(in srgb, var(--plum) 35%, transparent)',
                                            borderRadius: 11, padding: '14px 15px', background: 'var(--surface)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <span aria-hidden="true" style={{ width: 22, height: 22, borderRadius: '50%', background: 'var(--plum)',
                                          color: '#fff', fontSize: 12, fontWeight: 700, display: 'flex',
                                          alignItems: 'center', justifyContent: 'center' }}>+</span>
        <span style={{ fontSize: 13.5, fontWeight: 600 }}>New rule</span>
      </div>

      <RuleFields draft={draft} setDraft={setDraft} labelFor={(l) => l} />

      {/* The draft restated in the reader's words, live — and, once there is a real predicate to
          ask about, the live match count against the whole estate (lifecycle rules #4), fetched
          from the SAME evaluator the saved-rule preview uses. Neither needs the rule to exist. */}
      <RuleSentence match={match} action={draft.action} count={previewCount}
                    countOverride={matchProb ? ''
                      : previewBusy ? 'Checking how many files match…'
                      : previewErr ? 'Could not check how many files this would match — you can still add it disabled.'
                      : matchCountText(previewCount)} />

      <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <button className="small" onClick={add} disabled={busy || !!problem}>{busy ? 'Adding…' : 'Add rule'}</button>
        <span className="muted" style={{ fontSize: 12 }}>Added disabled — it tags nothing until you enable it.</span>
      </div>

      <p className="muted" style={{ fontSize: 12, margin: '8px 0 0', lineHeight: 1.5 }}>{spec.safety}</p>
      {problem && <p className="muted" style={{ fontSize: 12, margin: '6px 0 0' }}>{problem}</p>}
      {added && <p style={{ fontSize: 12.5, color: '#2F5310', margin: '8px 0 0' }} role="status">
        Added “{added}”. It is disabled — nothing is tagged until you enable it.
      </p>}
      {err && <p style={alertStyle} role="alert">⚠ {err}</p>}
    </div>
  )
}

function PrecedenceNote() {
  return (
    <div style={{ display: 'flex', gap: 9, alignItems: 'flex-start', marginTop: 14, padding: '10px 13px',
                  borderRadius: 9, background: '#FFF8E8', border: '1px solid #F0E0B6',
                  fontSize: 12.5, lineHeight: 1.55 }}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#8a6d1f" strokeWidth="1.8"
           strokeLinecap="round" style={{ flex: '0 0 auto', marginTop: 1 }} aria-hidden="true">
        <path d="M12 8v5" /><path d="M12 16.5v.5" /><circle cx="12" cy="12" r="9" />
      </svg>
      <div>
        A file matching both an archive and a deletion rule keeps the <b>archive</b> recommendation
        and is flagged for you to resolve. The safer outcome is never chosen silently.
      </div>
    </div>
  )
}

/**
 * @param embedded  true when this IS a screen rather than a section on one — wizard step 2.
 *
 * On the Discover tab this is one panel among many, so it collapses and carries its own title and
 * one-line description. As a wizard step it is the entire screen: the rail already says "Lifecycle
 * rules" and the wizard already prints the same description as the step subtitle, so rendering
 * them again is the duplicate-header defect, and a disclosure the user must open to see the step
 * they navigated to is a step that looks empty.
 */
export default function DispositionRules({ embedded = false }) {
  // Embedded, it starts open and stays open — there is nothing else on the screen to collapse in
  // favour of.
  const [open, setOpen] = useState(embedded)
  const [rules, setRules] = useState(null)   // null = not asked yet. NEVER rendered as "no rules".
  const [counts, setCounts] = useState({})   // policy_id -> would_match, only once actually asked
  const [err, setErr] = useState('')

  const load = useCallback(() => Promise.resolve(listDispositionPolicies())
    .then((rows) => {
      setRules((Array.isArray(rows) ? rows : []).filter((p) => LIFECYCLE_ACTIONS.has(p.action)))
      setErr('')
    })
    .catch((e) => setErr(refusalText(e))), [])

  useEffect(() => { if (open && rules == null && !err) load() }, [open, rules, err, load])

  const setCount = useCallback((id, n) => setCounts((c) => ({ ...c, [id]: n })), [])

  // A rule is created disabled, so previewing it straight away is safe and answers the question a
  // person actually has at that moment: what WOULD this match, before I enable it?
  const onCreated = useCallback((policyId) => {
    load()
    if (!policyId) return
    Promise.resolve(previewDispositionPolicy(policyId))
      .then((r) => setCount(policyId, r?.would_match ?? null))
      .catch(() => { /* the count stays unasked rather than becoming a zero */ })
  }, [load, setCount])

  // Duplicate = create a new rule with the same match/action/approval, a distinguishing name, and
  // no backend route of its own — createDispositionPolicy already makes it disabled, so a
  // duplicate starts exactly as safe as any new rule does.
  const onDuplicate = useCallback((p) => {
    const match = JSON.parse(p.match || '[]')
    const actionConfig = JSON.parse(p.action_config || '{}')
    return Promise.resolve(
      createDispositionPolicy(`${p.name} (copy)`, match, p.action, actionConfig, !!p.requires_approval)
    ).then((created) => onCreated(created && created.policy_id ? created.policy_id : null))
  }, [onCreated])

  // Swap with the adjacent rule and send the WHOLE new order — reorderDispositionPolicies takes
  // every id, not a single move, so this always sends a complete, unambiguous list.
  const onMove = useCallback((policyId, dir) => {
    const i = rules.findIndex((p) => p.policy_id === policyId)
    const j = dir === 'up' ? i - 1 : i + 1
    if (i < 0 || j < 0 || j >= rules.length) return Promise.resolve()
    const next = rules.slice()
    ;[next[i], next[j]] = [next[j], next[i]]
    return Promise.resolve(reorderDispositionPolicies(next.map((p) => p.policy_id))).then(() => load())
  }, [rules, load])

  const [conflicts, setConflicts] = useState(null)   // null = not checked yet
  const [conflictsErr, setConflictsErr] = useState('')
  const [conflictsBusy, setConflictsBusy] = useState(false)
  const checkConflicts = () => {
    setConflictsBusy(true); setConflictsErr('')
    Promise.resolve(listDispositionConflicts())
      .then((r) => setConflicts(Array.isArray(r?.conflicts) ? r.conflicts : []))
      .catch((e) => setConflictsErr(refusalText(e)))
      .finally(() => setConflictsBusy(false))
  }

  const enabledCount = rules == null ? null : rules.filter((p) => p.enabled).length

  return (
    <section className="disprules"
             style={{ marginTop: embedded ? 0 : 12, border: embedded ? 'none' : line,
                      borderRadius: 10, padding: embedded ? 0 : '10px 14px' }}>
      {!embedded && (
        <>
          <button className="linklike" onClick={() => setOpen((o) => !o)} aria-expanded={open}
                  style={{ fontWeight: 700, fontSize: 13.5, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span aria-hidden="true">{open ? '▾' : '▸'}</span> Lifecycle rules
          </button>
          <div className="muted" style={{ fontSize: 12, marginTop: 3, lineHeight: 1.5 }}>
            Rules run during discovery and <b>tag</b> matching files. Nothing is moved, trashed or changed.
          </div>
        </>
      )}

      {open && (
        <div style={{ marginTop: 14 }}>
          <h3 style={{ margin: '0 0 4px', fontSize: 13, fontWeight: 600, color: 'var(--muted)', letterSpacing: '.04em' }}>
            RULES
          </h3>
          <p className="muted" style={{ fontSize: 12.5, margin: '0 0 14px', lineHeight: 1.5 }}>
            Each rule applies one recommendation to the files it matches. Rules are evaluated in order;
            a file may carry only one recommendation.
          </p>

          {err && <p style={alertStyle} role="alert">⚠ {err}</p>}

          {/* rules == null renders NOTHING for the list — not an empty state, not a count. An
              unanswered question and an empty answer are different facts. */}
          {rules != null && (rules.length === 0
            ? <p className="muted" style={{ fontSize: 12.5, margin: '0 0 10px' }}>
                No lifecycle rules yet. Add one below — it starts disabled.
              </p>
            : rules.map((p, i) => (
                <RuleRow key={p.policy_id} p={p} count={counts[p.policy_id] ?? null} rank={i + 1}
                         isFirst={i === 0} isLast={i === rules.length - 1}
                         onCount={setCount} onChanged={load} onDuplicate={onDuplicate} onMove={onMove} />
              )))}

          <NewRule onCreated={onCreated} />
          <PrecedenceNote />

          {rules != null && rules.length > 1 && (
            <div style={{ marginTop: 14, borderTop: line, paddingTop: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <button className="ghost small" onClick={checkConflicts} disabled={conflictsBusy}>
                  {conflictsBusy ? 'Checking…' : 'Check for rule conflicts'}
                </button>
                <span className="muted" style={{ fontSize: 12 }}>
                  Files matched by more than one enabled rule, and which one wins right now.
                </span>
              </div>
              {conflictsErr && <p style={alertStyle} role="alert">⚠ {conflictsErr}</p>}
              {conflicts != null && (conflicts.length === 0
                ? <p className="muted" style={{ fontSize: 12.5, margin: '8px 0 0' }}>
                    No file matches more than one enabled rule.
                  </p>
                : conflicts.map((c) => (
                    <div key={c.doc_id} style={{ border: line, borderRadius: 8, padding: '8px 11px', marginTop: 8, fontSize: 12.5 }}>
                      <div style={{ fontWeight: 600 }}>{c.path || c.doc_id}</div>
                      <div className="muted" style={{ margin: '3px 0' }}>
                        Matches {c.matched_rules.map((r) => `"${r.name}"`).join(', ')}
                      </div>
                      <div>Wins: <b>{c.winner ? c.winner.name : '—'}</b> — {c.reason}</div>
                    </div>
                  )))}
            </div>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, borderTop: line,
                        paddingTop: 12, marginTop: 14 }}>
            <span className="muted" style={{ fontSize: 12.5 }}>
              {enabledCount == null
                ? (err ? 'Rule list unavailable.' : 'Loading rules…')
                : `${enabledCount} of ${rules.length} rule${rules.length === 1 ? '' : 's'} enabled`}
            </span>
          </div>
        </div>
      )}
    </section>
  )
}

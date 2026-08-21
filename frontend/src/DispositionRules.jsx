import { useState, useEffect, useCallback } from 'react'
import {
  listDispositionPolicies, createDispositionPolicy, setDispositionPolicyEnabled, previewDispositionPolicy,
} from './api.js'
import {
  ACTIONS, CONDITIONS, LIFECYCLE_ACTIONS, actionSpec, draftProblem, draftToMatch, emptyDraft,
  matchCountText, refusalText, ruleSentenceParts,
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
// DELIBERATELY NOT HERE: an "Edit" button and a match count for an UNSAVED draft. Neither has a
// backend — there is no policy-update route, and preview is POST /policies/{id}/preview, which
// needs a saved id. Rather than fake either, the draft gets a plain-language restatement (which
// needs no server) and the real count is fetched the moment the rule exists — still disabled, so
// "before it is enabled" is preserved.

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

function RuleRow({ p, count, onCount, onChanged }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const enabled = !!p.enabled

  const toggle = () => {
    setBusy(true); setErr('')
    Promise.resolve(setDispositionPolicyEnabled(p.policy_id, !enabled))
      .then(() => onChanged())
      .catch((e) => setErr(refusalText(e)))
      .finally(() => setBusy(false))
  }
  const runPreview = () => {
    setBusy(true); setErr('')
    Promise.resolve(previewDispositionPolicy(p.policy_id))
      // `?? null` and not `?? 0`: a response without a count is an unanswered question, and
      // rendering it as zero would be the measured-zero lie this screen exists to avoid.
      .then((r) => onCount(p.policy_id, r?.would_match ?? null))
      .catch((e) => setErr(refusalText(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div className="lifecycle-rule" style={{ border: line, borderRadius: 11, padding: '13px 15px', marginBottom: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <input type="checkbox" checked={enabled} onChange={toggle} disabled={busy}
               aria-label={`Enable rule ${p.name}`} style={{ width: 15, height: 15 }} />
        <span style={{ fontSize: 13.5, fontWeight: 600 }}>{p.name}</span>
        <ActionTag action={p.action} />
        <span className="muted" style={{ fontSize: 12 }}>{enabled ? 'Enabled' : 'Disabled — tags nothing yet'}</span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button className="ghost small" onClick={runPreview} disabled={busy}>Preview matches</button>
        </span>
      </div>
      <RuleSentence match={p.match} action={p.action} count={count} />
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

  const setValue = (key, v) => setDraft((d) => ({ ...d, values: { ...d.values, [key]: v } }))

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

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          <span style={fieldLabel}>Name</span>
          <input style={inp} type="text" value={draft.name} aria-label="Rule name"
                 placeholder="e.g. Finance retention"
                 onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          <span style={fieldLabel}>Action</span>
          <select style={inp} value={draft.action} aria-label="Action"
                  onChange={(e) => setDraft((d) => ({ ...d, action: e.target.value }))}>
            {ACTIONS.map((a) => <option key={a.action} value={a.action}>{a.label}</option>)}
          </select>
        </label>
        {CONDITIONS.map((c) => (
          <label key={c.key} style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            <span style={fieldLabel}>{c.label}{c.unit ? ` (${c.unit})` : ''}</span>
            <input style={inp} aria-label={c.label} placeholder={c.placeholder}
                   type={c.kind === 'date' ? 'date' : 'text'}
                   inputMode={c.kind === 'number' ? 'numeric' : undefined}
                   value={draft.values[c.key]} onChange={(e) => setValue(c.key, e.target.value)} />
          </label>
        ))}
      </div>

      {/* The draft restated in the reader's words, live. It needs no server, so it is available
          at the moment the choice is being made rather than after the rule exists. */}
      <RuleSentence match={match} action={draft.action} count={null}
                    countOverride={problem ? '' : 'Add the rule to see how many files match — it is added disabled.'} />

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
            : rules.map((p) => (
                <RuleRow key={p.policy_id} p={p} count={counts[p.policy_id] ?? null}
                         onCount={setCount} onChanged={load} />
              )))}

          <NewRule onCreated={onCreated} />
          <PrecedenceNote />

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

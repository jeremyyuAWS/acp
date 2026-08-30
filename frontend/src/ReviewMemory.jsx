import { useCallback, useEffect, useState } from 'react'
import { getOrgMemory, addOrgMemoryRule, setOrgMemoryStatus, deriveOrgMemory } from './api.js'
import { normalizeOrgMemory, AUTHORABLE_KINDS } from './reviewMemory.js'

// ADR 0021 · Settings → Review Memory — the org's house style, and the decisions on rules the
// derivation job proposes from real reviewer behaviour.
//
// The backend for all of this shipped and had no client at all: `GET/POST /org-memory`,
// `POST /org-memory/derive` and `PUT /org-memory/{id}/status` were live, admin-gated and tested,
// with nothing in the SPA calling them (found by a 2026-08-30 audit). This is that panel.
//
// THREE HONESTY RULES SHAPE EVERY PART OF THIS SCREEN.
//
// 1. AN ACTIVE RULE IS NOT NECESSARILY A RULE IN EFFECT. `ACP_REVIEW_MEMORY` defaults OFF, and
//    with it off `memory.guidance_for` returns "" — the model prompt is byte-for-byte what it was
//    before ADR 0021. So the panel leads with how many rules are ACTUALLY shaping drafts
//    (`effectiveCount`), and when the flag is off it says the rules are stored but inert. Listing
//    them under a green "active" and stopping there would be the precise lie this repo keeps
//    writing regression tests against.
//
// 2. WRITE CONTROLS RENDER ONLY FOR AN ADMIN. Every write is `_require_admin` server-side. #952
//    is the reason this is not left to the backend: WorkerReplicaControl rendered its buttons for
//    everyone, a non-admin's click optimistically updated and then silently reverted on the 403,
//    and nothing said why. A non-admin here sees the same rules, read-only, with a line saying so.
//
// 3. EVIDENCE IS QUOTED, NOT CHARACTERISED. A derived proposal shows the counts its row carries
//    ("Reviewers edited 8 of 10 drafts — median 34 characters shorter") and no adjective. There is
//    no confidence score, no "strong signal", no percentage this panel computed. ADR 0016 and the
//    ADR 0021 gate both turn on the human reading the real number and deciding.
//
// NO EDIT BUTTON, and that is deliberate rather than unfinished. ADR 0021 sketches
// "[Accept] [Dismiss] [Edit]", but there is no endpoint that rewrites a rule's guidance — the only
// mutation is `PUT .../status`. Offering Edit would be offering a control that cannot work. The
// honest equivalent is available and named in the copy: dismiss the proposal, then author the
// wording you actually want, which the form below does.

const kicker = { fontSize: 11.5, letterSpacing: '.07em', textTransform: 'uppercase',
                 color: 'var(--muted)', fontWeight: 600 }
const muted = { fontSize: 12, color: 'var(--muted)', lineHeight: 1.55 }

function Scope({ rule }) {
  // NULL rule_id/format mean "applies everywhere". Saying so beats an empty cell, which reads as
  // data that failed to load.
  return (
    <span className="muted" style={{ fontSize: 11.5 }}>
      {rule.ruleId ? `WCAG ${rule.ruleId}` : 'all criteria'}
      {' · '}
      {rule.format ? rule.format.toUpperCase() : 'all formats'}
    </span>
  )
}

function Rule({ rule, canWrite, busy, onStatus }) {
  return (
    <li className="rm-rule" data-status={rule.status} data-kind={rule.kind}
        style={{ padding: '10px 0', borderTop: '1px solid var(--line)' }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <span style={{ ...kicker, fontSize: 10.5 }}>{rule.kindLabel}</span>
        <Scope rule={rule} />
        {rule.effective && <span className="rm-effective" style={{ fontSize: 11, color: '#1F4D22' }}>
          in effect
        </span>}
      </div>
      <div style={{ fontSize: 13, marginTop: 3, wordBreak: 'break-word' }}>{rule.guidance}</div>

      {rule.evidence && (
        <div className="rm-evidence" style={{ ...muted, marginTop: 3 }}>{rule.evidence}</div>
      )}
      {rule.evidenceMissing && (
        <div className="rm-evidence-missing" style={{ ...muted, marginTop: 3 }}>
          This proposal recorded evidence that could not be read. Treat the guidance on its own
          merits rather than as measured — and it is worth reporting.
        </div>
      )}

      {canWrite && (
        <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
          {rule.status === 'proposed' && (
            <>
              <button className="ghost small" disabled={busy}
                      onClick={() => onStatus(rule.id, 'active')}>Accept</button>
              <button className="ghost small" disabled={busy}
                      onClick={() => onStatus(rule.id, 'archived')}>Dismiss</button>
            </>
          )}
          {rule.status === 'active' && (
            <button className="ghost small" disabled={busy}
                    onClick={() => onStatus(rule.id, 'archived')}>Retire</button>
          )}
          {rule.status === 'archived' && (
            <button className="ghost small" disabled={busy}
                    onClick={() => onStatus(rule.id, 'active')}>Restore</button>
          )}
        </div>
      )}
    </li>
  )
}

function AuthorForm({ busy, onAdd }) {
  const [kind, setKind] = useState('style')
  const [guidance, setGuidance] = useState('')
  const [ruleId, setRuleId] = useState('')
  const [format, setFormat] = useState('')
  const trimmed = guidance.trim()
  return (
    <form className="rm-author" style={{ marginTop: 14 }}
          onSubmit={(e) => {
            e.preventDefault()
            if (!trimmed) return
            onAdd({ kind, guidance: trimmed, ruleId: ruleId.trim() || null,
                    format: format.trim() || null })
              .then(() => { setGuidance(''); setRuleId(''); setFormat('') })
              .catch(() => { /* the panel renders the error; keep what was typed */ })
          }}>
      <div style={kicker}>Author a rule</div>
      <p style={{ ...muted, margin: '4px 0 8px' }}>
        A rule you write applies immediately — a human wrote it, so it does not wait for evidence.
        Leave the scope fields empty to apply it to every criterion and format.
      </p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <label style={muted}>
          Kind{' '}
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Rule kind">
            {AUTHORABLE_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </label>
        <input aria-label="WCAG criterion (optional)" placeholder="1.1.1 (optional)"
               value={ruleId} onChange={(e) => setRuleId(e.target.value)} style={{ width: 130 }} />
        <input aria-label="Format (optional)" placeholder="docx (optional)"
               value={format} onChange={(e) => setFormat(e.target.value)} style={{ width: 130 }} />
      </div>
      <textarea aria-label="Guidance" rows={2} value={guidance} placeholder="Keep alt text under 120 characters."
                onChange={(e) => setGuidance(e.target.value)}
                style={{ width: '100%', marginTop: 8, fontSize: 13 }} />
      <button className="primary small" type="submit" disabled={busy || !trimmed}
              style={{ marginTop: 6 }}>Add rule</button>
    </form>
  )
}

export default function ReviewMemory({ me = null }) {
  const canWrite = !!me?.is_admin
  const [model, setModel] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState(null)

  const load = useCallback(() => {
    setErr(null)
    return getOrgMemory()
      .then((raw) => setModel(normalizeOrgMemory(raw)))
      .catch(() => setErr('Review memory could not be read. That is a problem reaching the server, '
                          + 'not a statement about your house style.'))
  }, [])

  useEffect(() => { load() }, [load])

  // Every write refetches rather than patching local state: the backend is the authority on
  // status, and a panel that optimistically renders a change it did not confirm is how #952's bug
  // looked to a non-admin.
  const run = (fn, describe) => {
    setBusy(true); setErr(null); setNote(null)
    return fn()
      .then((res) => { setNote(describe(res)); return load() })
      .catch(() => setErr('That change did not go through. If you are not an administrator, only '
                          + 'an administrator can edit review memory.'))
      .finally(() => setBusy(false))
  }

  const onStatus = (id, status) => run(() => setOrgMemoryStatus(id, status),
    () => (status === 'active' ? 'Rule is now active.'
      : status === 'archived' ? 'Rule retired.' : 'Rule set back to proposed.'))

  const onAdd = (patch) => run(() => addOrgMemoryRule(patch), () => 'Rule added.')

  const onDerive = () => run(deriveOrgMemory, (res) => (res?.count
    ? `${res.count} proposal${res.count === 1 ? '' : 's'} added below.`
    : 'No new proposals — there is not enough recent review signal to support one yet.'))

  if (err && !model) {
    return <section className="rm-panel"><p className="rm-error" style={muted}>{err}</p></section>
  }
  if (!model) return <section className="rm-panel"><p style={muted}>Loading…</p></section>
  if (!model.available) {
    return <section className="rm-panel"><p style={muted}>Review memory is unavailable.</p></section>
  }

  const groups = [
    ['Awaiting your decision', model.proposed],
    ['Active', model.active],
    ['Retired', model.archived],
  ]

  return (
    <section className="rm-panel" style={{ maxWidth: 640 }}>
      <h3 style={{ margin: 0, fontSize: 15, fontWeight: 650 }}>Review memory</h3>
      <p style={{ ...muted, marginTop: 6 }}>
        House style ACP applies to AI-drafted text, plus rules proposed from how your reviewers
        actually edit drafts. Nothing here changes a model — it changes what ACP asks for.
      </p>

      {/* The load-bearing line. Rule 1 in this file's header. */}
      {model.enabled ? (
        <p className="rm-state" style={{ ...muted, marginTop: 8 }}>
          <b style={{ color: 'var(--ink)' }}>{model.effectiveCount}</b>{' '}
          {model.effectiveCount === 1 ? 'rule is' : 'rules are'} shaping drafts right now.
        </p>
      ) : (
        <p className="rm-state rm-disabled" style={{ ...muted, marginTop: 8 }}>
          <b style={{ color: 'var(--ink)' }}>Review memory is switched off</b> for this deployment
          (<code>ACP_REVIEW_MEMORY</code>). Rules below are stored and editable, but{' '}
          <b style={{ color: 'var(--ink)' }}>none of them is shaping any draft</b> — prompts are
          exactly what they would be without this feature.
        </p>
      )}

      {!canWrite && (
        <p className="rm-readonly" style={{ ...muted, marginTop: 6 }}>
          Read-only: editing review memory is limited to administrators.
        </p>
      )}

      {err && <p className="rm-error" style={{ ...muted, marginTop: 6 }}>{err}</p>}
      {note && <p className="rm-note" style={{ ...muted, marginTop: 6 }}>{note}</p>}

      {canWrite && (
        <div style={{ marginTop: 10 }}>
          <button className="ghost small" disabled={busy} onClick={onDerive}>
            Look for new proposals
          </button>
          <span style={{ ...muted, marginLeft: 8 }}>
            Reads recent review decisions and proposes rules the counts support. Proposals are never
            applied automatically.
          </span>
        </div>
      )}

      {model.counts.total === 0 && (
        <p className="rm-empty" style={{ ...muted, marginTop: 12 }}>
          No rules yet. Author one below, or look for proposals once reviewers have edited enough
          drafts for a pattern to be measurable.
        </p>
      )}

      {groups.map(([title, rules]) => rules.length > 0 && (
        <div key={title} style={{ marginTop: 14 }}>
          <div style={kicker}>{title} ({rules.length})</div>
          <ul style={{ listStyle: 'none', margin: '4px 0 0', padding: 0 }}>
            {rules.map((r) => (
              <Rule key={r.id} rule={r} canWrite={canWrite} busy={busy} onStatus={onStatus} />
            ))}
          </ul>
          {title === 'Awaiting your decision' && canWrite && (
            <p style={{ ...muted, marginTop: 6 }}>
              To reword a proposal rather than accept it as written: dismiss it, then author the
              wording you want below.
            </p>
          )}
        </div>
      ))}

      {canWrite && <AuthorForm busy={busy} onAdd={onAdd} />}
    </section>
  )
}

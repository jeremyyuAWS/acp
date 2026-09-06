import { useEffect, useState } from 'react'
import { getArchivePolicy, updateArchivePolicy, setArchiveKillSwitch } from './api.js'
import { AGE_WARNING, policyProblem, policySummary, refusalText, killSwitchOn } from './archiveAutofire.js'

// Discover, step 2 — the "Automatically archive proven superseded files" option on the lifecycle
// rule editor (DispositionRules.jsx renders this beneath the rule list).
//
// THIS IS THE ONE SCREEN WHERE SOMEBODY AUTHORISES UNATTENDED FILE MOVEMENT, and everything about
// its layout follows from that. The four facts the PRD requires at the point of the decision —
// the evidence required, the destination, the daily ceiling, and whether this is a dry run — are
// rendered as a labelled list the moment the option is switched on, not behind a "details" link,
// because a person who has to go looking for them has already made the decision without them.
//
// THE AGE WARNING IS NOT A FOOTNOTE. Every rule on this screen is written with a date or an age
// condition; the reader's working assumption when they see an "automatically archive" toggle on
// such a rule is that the rule's own condition is what will fire it. That assumption is wrong and
// dangerous, so the correction sits next to the control, in plain words, always visible — the
// same treatment lifecycleRules.js gives the recoverable-delete fact for the same reason.
//
// SAFETY, mirrored from the backend rather than asserted here:
//   * The policy ships DISABLED and in DRY RUN (api/archive_autofire.POLICY_DEFAULTS), so the
//     option existing changes nothing until somebody turns it on and then turns dry run off.
//   * Writing the policy is admin-gated and running it is owner-gated server-side. A refusal is
//     surfaced inline next to the control, because a policy that silently failed to save is
//     indistinguishable from one that exists.
//   * `policyProblem` here only decides what to OFFER; the server refuses regardless.

const line = '1px solid var(--line)'
const box = { border: line, borderRadius: 10, padding: '12px 14px', marginTop: 12 }
const label = { fontSize: 11.5, fontWeight: 600, letterSpacing: '.03em', color: 'var(--muted)',
                textTransform: 'uppercase' }
const alertStyle = { fontSize: 12.5, color: 'var(--error-fg-strong)', margin: '8px 0 0', lineHeight: 1.5 }

export default function ArchiveAutofireOption({ rules = [] }) {
  const [state, setState] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loadFailed, setLoadFailed] = useState(false)

  useEffect(() => {
    let live = true
    // Called through Promise.resolve().then so a HOST that exposes only part of the api.js
    // surface — an embedded shell, or an older test double mocking the disposition subset —
    // turns a missing export into a rejection this component reports, rather than a synchronous
    // throw that unmounts the whole rule editor around it. The same guard LiveOpsAiSummary uses,
    // for the same reason. Missing settings become "unavailable", never a render error.
    Promise.resolve().then(() => getArchivePolicy())
      .then((value) => { if (live) { setState(value); setLoadFailed(false) } })
      .catch(() => { if (live) setLoadFailed(true) })
    return () => { live = false }
  }, [])

  const save = (patch) => {
    setBusy(true); setError('')
    return Promise.resolve().then(() => updateArchivePolicy(patch))
      .then((value) => setState(value))
      .catch((e) => setError(refusalText(e)))
      .finally(() => setBusy(false))
  }

  if (loadFailed) {
    return <section style={box} role="status">
      <b>Automatic archiving is unavailable</b>
      <p className="muted" style={{ fontSize: 12.5, margin: '4px 0 0' }}>
        Its settings could not be loaded, so ACP cannot say whether it is on or off. Lifecycle rules
        above are unaffected and still produce recommendations.
      </p>
    </section>
  }
  if (!state) return <section style={box} className="muted">Loading automatic-archive settings…</section>

  const policy = state.policy || {}
  const on = !!policy.enabled
  const problem = policyProblem({ ...policy, enabled: true })
  const evidenceTypes = state.evidence_types || []

  const toggleEvidence = (type) => {
    const current = new Set(policy.required_evidence || [])
    if (current.has(type)) current.delete(type); else current.add(type)
    save({ required_evidence: [...current] })
  }
  const toggleRule = (ruleId) => {
    const current = new Set((policy.rule_ids || []).map(String))
    if (current.has(String(ruleId))) current.delete(String(ruleId)); else current.add(String(ruleId))
    save({ rule_ids: [...current] })
  }

  // `data-archive-autofire` marks the one block on this screen that is allowed to say a file IS
  // archived. Everything else here describes rules, which only ever tag — and
  // DispositionRules.test.jsx sweeps the screen for exactly that claim. The marker lets that
  // sweep keep its full strength over the rule copy while this block, which has its own
  // vocabulary tests, is excluded by name rather than by the guard being weakened for everyone.
  return <section style={box} data-archive-autofire="" aria-labelledby="archive-autofire-heading">
    <h3 id="archive-autofire-heading" style={{ margin: 0, fontSize: 14 }}>
      Automatically archive proven superseded files
    </h3>

    {/* Always visible, on or off. The reader's wrong assumption is formed by the toggle's
        existence, not by its state, so the correction cannot be conditional on it. */}
    <p style={{ fontSize: 12.5, lineHeight: 1.55, margin: '6px 0 0' }}>{AGE_WARNING}</p>

    <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', marginTop: 10 }}>
      <input type="checkbox" checked={on} disabled={busy}
             onChange={(e) => save({ enabled: e.target.checked })} />
      <span>
        <b>Archive proven superseded files without asking me</b>
        <span className="muted" style={{ display: 'block', fontSize: 12.5, lineHeight: 1.5 }}>
          Only files with the evidence chosen below. Everything else stays a recommendation.
        </span>
      </span>
    </label>

    {!on && problem && <p className="muted" style={{ fontSize: 12.5, margin: '8px 0 0' }}>
      Before this can be turned on: {problem}
    </p>}

    {on && <div style={{ marginTop: 12, display: 'grid', gap: 12 }}>
      <fieldset style={{ border: line, borderRadius: 8, padding: '8px 12px 12px', margin: 0 }}>
        <legend style={label}>Evidence required</legend>
        {evidenceTypes.map((e) => <label key={e.type} style={{ display: 'flex', gap: 8, marginTop: 6 }}>
          <input type="checkbox" disabled={busy}
                 checked={(policy.required_evidence || []).includes(e.type)}
                 onChange={() => toggleEvidence(e.type)} />
          <span style={{ fontSize: 12.5, lineHeight: 1.45 }}>{e.label}</span>
        </label>)}
      </fieldset>

      <fieldset style={{ border: line, borderRadius: 8, padding: '8px 12px 12px', margin: 0 }}>
        <legend style={label}>Lifecycle rules this applies to</legend>
        {!rules.length && <p className="muted" style={{ fontSize: 12.5, margin: '6px 0 0' }}>
          No archive rules exist yet. Create one above first.
        </p>}
        {rules.map((r) => <label key={r.policy_id} style={{ display: 'flex', gap: 8, marginTop: 6 }}>
          <input type="checkbox" disabled={busy}
                 checked={(policy.rule_ids || []).map(String).includes(String(r.policy_id))}
                 onChange={() => toggleRule(r.policy_id)} />
          <span style={{ fontSize: 12.5 }}>{r.name || 'Unnamed rule'}</span>
        </label>)}
      </fieldset>

      <label style={{ display: 'grid', gap: 4 }}>
        <span style={label}>Archive destination</span>
        <input value={policy.archive_root || ''} disabled={busy}
               placeholder="e.g. Archive/Superseded"
               onChange={(e) => setState({ ...state, policy: { ...policy, archive_root: e.target.value } })}
               onBlur={(e) => save({ archive_root: e.target.value })} />
      </label>

      <label style={{ display: 'flex', gap: 8 }}>
        <input type="checkbox" checked={!!policy.preserve_hierarchy} disabled={busy}
               onChange={(e) => save({ preserve_hierarchy: e.target.checked })} />
        <span style={{ fontSize: 12.5 }}>Keep the original folder structure beneath the destination</span>
      </label>

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <label style={{ display: 'grid', gap: 4 }}>
          <span style={label}>Most files per day</span>
          <input type="number" min="1" value={policy.max_actions_per_day ?? ''} disabled={busy}
                 onChange={(e) => setState({ ...state, policy: { ...policy, max_actions_per_day: e.target.value } })}
                 onBlur={(e) => save({ max_actions_per_day: Number(e.target.value) })} />
        </label>
        <label style={{ display: 'grid', gap: 4 }}>
          <span style={label}>Most files per run</span>
          <input type="number" min="1" value={policy.max_actions_per_run ?? ''} disabled={busy}
                 onChange={(e) => setState({ ...state, policy: { ...policy, max_actions_per_run: e.target.value } })}
                 onBlur={(e) => save({ max_actions_per_run: Number(e.target.value) })} />
        </label>
        <label style={{ display: 'grid', gap: 4 }}>
          <span style={label}>Replacement must be at least</span>
          <input type="number" min="0" value={policy.min_replacement_age_days ?? ''} disabled={busy}
                 onChange={(e) => setState({ ...state, policy: { ...policy, min_replacement_age_days: e.target.value } })}
                 onBlur={(e) => save({ min_replacement_age_days: Number(e.target.value) })} />
        </label>
      </div>

      <label style={{ display: 'flex', gap: 8 }}>
        <input type="checkbox" checked={!!policy.dry_run} disabled={busy}
               onChange={(e) => save({ dry_run: e.target.checked })} />
        <span style={{ fontSize: 12.5 }}>
          <b>Dry run</b> — run every safety check against the real source and move nothing
        </span>
      </label>

      <dl style={{ display: 'grid', gridTemplateColumns: 'minmax(120px,170px) 1fr', gap: 6,
                   margin: 0, fontSize: 12.5, lineHeight: 1.5 }}>
        {policySummary(policy).map((row) => <div key={row.label} style={{ display: 'contents' }}>
          <dt style={label}>{row.label}</dt><dd style={{ margin: 0 }}>{row.value}</dd>
        </div>)}
      </dl>

      <div>
        <button type="button" disabled={busy}
                onClick={() => Promise.resolve().then(() => setArchiveKillSwitch(!killSwitchOn(policy)))
                  .then(setState).catch((e) => setError(refusalText(e)))}>
          {killSwitchOn(policy) ? 'Turn the kill switch off' : 'Stop all automatic archiving now'}
        </button>
        {killSwitchOn(policy) && <p role="status" style={{ fontSize: 12.5, margin: '6px 0 0' }}>
          <b>Kill switch on.</b> No new moves are started. Anything already in flight is finished
          or explicitly failed, and recorded either way.
        </p>}
      </div>
    </div>}

    {error && <p role="alert" style={alertStyle}>{error}</p>}
  </section>
}

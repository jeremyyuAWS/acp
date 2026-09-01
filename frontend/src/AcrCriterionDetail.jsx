import { useEffect, useState } from 'react'
import { getAcrCriterion, addAcrEvidence, decideAcrCriterion, approveAcrCriterion,
         FINAL_STATUSES, REMARKS_REQUIRED } from './acrApi'

// PRD §15 "Criterion detail" — the requirement, its evidence, the draft recommendation, the final
// decision and the remarks.
//
// THE ONE RULE THIS SCREEN FOLLOWS. It never computes whether a status is allowed. The backend
// returns `assessment.permitted_statuses` and `assessment.refusals`, and this renders exactly
// those — so the button set and the refusal text are the server's, not a local re-derivation that
// could drift from it. A screen that offered "Supports" and then showed a 422 would train users to
// treat the gate as a glitch.
//
// A REFUSAL IS SHOWN, NOT HIDDEN. Disallowed statuses stay visible and disabled, with the reason
// next to them. Removing them would leave a user unable to tell "this is not permitted yet, and
// here is what would permit it" from "this feature is broken" — and the reason is the actionable
// half (PRD §4.4: make limitations visible).

const RESULTS = ['pass', 'fail', 'not_applicable', 'blocked']

// Mirrors the backend's acr_model source kinds. Keyboard and screen-reader are listed separately
// from "manual" because PRD §14 wants them recorded as distinct methods.
const SOURCE_KINDS = [
  ['manual', 'Manual evaluation'],
  ['keyboard', 'Keyboard test'],
  ['screen_reader', 'Screen-reader test'],
  ['visual', 'Visual inspection'],
  ['code', 'Code inspection'],
  ['automated', 'Automated tool'],
]

export default function AcrCriterionDetail({ reportId, criterionNum, canEdit, canApprove, onChange }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [remarks, setRemarks] = useState('')
  const [ev, setEv] = useState({ source_kind: 'manual', result: 'pass', method: '', browser: '',
                                 environment: '', notes: '', tool_name: '', tool_version: '',
                                 rule_id: '', coverage: 'partial' })

  const load = async () => {
    try {
      const d = await getAcrCriterion(reportId, criterionNum)
      setData(d)
      setStatus(d.criterion.final_status || '')
      setRemarks(d.criterion.remarks || '')
      setError(null)
    } catch (e) { setError(String(e.message || e)) }
  }

  useEffect(() => { load() /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [reportId, criterionNum])

  if (error) return <p role="alert" className="lockwarn">{error}</p>
  if (!data) return <p className="muted">Loading criterion…</p>

  const { criterion, evidence, assessment } = data
  const permitted = assessment?.permitted_statuses || {}
  const refusals = assessment?.refusals || {}

  const act = async (fn, msg) => {
    setBusy(true); setError(null)
    try { await fn(); await load(); onChange?.(); setStatus(msg) }
    catch (e) { setError(String(e.message || e)) }
    finally { setBusy(false) }
  }

  const submitEvidence = (e) => {
    e.preventDefault()
    const payload = { ...ev }
    // Coverage is meaningless for human evidence and REQUIRED for automated — the backend refuses
    // an automated row without it, so the field only travels when it applies.
    if (payload.source_kind !== 'automated') {
      delete payload.coverage; delete payload.tool_name; delete payload.tool_version; delete payload.rule_id
    }
    return act(() => addAcrEvidence(reportId, criterionNum, payload), 'Evidence recorded.')
  }

  return (
    <section aria-labelledby="acr-crit-heading">
      <h3 id="acr-crit-heading">
        {criterion.criterion_num} {criterion.criterion_name}
        <span className="muted"> · Level {criterion.level}</span>
      </h3>
      <p className="muted">{criterion.principle} · {criterion.guideline}</p>

      {/* role=status so a change announces itself — 4.1.3, which this very report asserts. */}
      <p role="status" aria-live="polite" className="muted">{status}</p>
      {error && <p role="alert" className="lockwarn">{error}</p>}

      {/* ── what ACP suggests, explicitly labelled as a suggestion (PRD §20) ── */}
      <div className="acr-draft">
        <h4>ACP's assessment</h4>
        {assessment?.draft_status
          ? <p><strong>Draft suggestion: {assessment.draft_status}</strong> <span className="muted">— a suggestion, not a decision. A person selects the final status.</span></p>
          : <p><strong>No draft suggestion.</strong></p>}
        <p className="muted">{assessment?.draft_reason}</p>
        <p className="muted">
          {assessment?.evidence_live} live evidence record(s)
          {assessment?.evidence_stale ? `, ${assessment.evidence_stale} stale (retained for audit history)` : ''}
          {assessment?.automated_only ? ' · automated only' : ''}
        </p>
      </div>

      {/* ── evidence ── */}
      <h4>Evidence</h4>
      {evidence.length === 0 ? <p className="muted">No evidence attached yet.</p> : (
        <table>
          <caption className="sr-only">Evidence for {criterion.criterion_num}</caption>
          <thead>
            <tr>
              <th scope="col">Type</th><th scope="col">Result</th><th scope="col">Tester</th>
              <th scope="col">Tested</th><th scope="col">Version</th><th scope="col">Details</th>
            </tr>
          </thead>
          <tbody>
            {evidence.map((e) => (
              <tr key={e.id}>
                <td>{e.source_kind}</td>
                <td>{e.result}</td>
                <td>{e.tester || '—'}</td>
                <td>{e.tested_at ? new Date(e.tested_at).toLocaleDateString() : '—'}</td>
                <td>{e.product_version || '—'}</td>
                <td>
                  {e.tool_name ? `${e.tool_name} ${e.tool_version || ''} · ${e.rule_id || ''} · coverage ${e.coverage}` : (e.method || e.notes || '—')}
                  {/* Stale is stated in words, never by colour alone — 1.4.1. */}
                  {e.stale_reason && <><br /><span className="acr-stale">Stale: {e.stale_reason.replace(/_/g, ' ')} — retained for audit history, cannot support publication</span></>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {canEdit && (
        <form onSubmit={submitEvidence}>
          <h4>Record evidence</h4>
          <label htmlFor="acr-ev-kind">Evidence type</label>
          <select id="acr-ev-kind" value={ev.source_kind}
                  onChange={(e) => setEv({ ...ev, source_kind: e.target.value })}>
            {SOURCE_KINDS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>

          <label htmlFor="acr-ev-result">Result</label>
          <select id="acr-ev-result" value={ev.result}
                  onChange={(e) => setEv({ ...ev, result: e.target.value })}>
            {RESULTS.map((r) => <option key={r} value={r}>{r.replace(/_/g, ' ')}</option>)}
          </select>

          {ev.source_kind === 'automated' ? (
            <>
              <label htmlFor="acr-ev-tool">Tool name</label>
              <input id="acr-ev-tool" value={ev.tool_name}
                     onChange={(e) => setEv({ ...ev, tool_name: e.target.value })} required />
              <label htmlFor="acr-ev-toolver">Tool version</label>
              <input id="acr-ev-toolver" value={ev.tool_version}
                     onChange={(e) => setEv({ ...ev, tool_version: e.target.value })} />
              <label htmlFor="acr-ev-rule">Rule ID</label>
              <input id="acr-ev-rule" value={ev.rule_id}
                     onChange={(e) => setEv({ ...ev, rule_id: e.target.value })} />
              <label htmlFor="acr-ev-coverage">
                Coverage of this criterion
                <span className="muted"> — how much of the criterion this technique actually reaches</span>
              </label>
              <select id="acr-ev-coverage" value={ev.coverage}
                      onChange={(e) => setEv({ ...ev, coverage: e.target.value })}>
                <option value="declared">declared — no technique yet</option>
                <option value="heuristic">heuristic — a proxy signal</option>
                <option value="partial">partial — sound over a subset</option>
                <option value="full">full — the whole criterion</option>
              </select>
            </>
          ) : (
            <>
              <label htmlFor="acr-ev-method">Test method</label>
              <input id="acr-ev-method" value={ev.method}
                     onChange={(e) => setEv({ ...ev, method: e.target.value })} />
              <label htmlFor="acr-ev-browser">Browser</label>
              <input id="acr-ev-browser" value={ev.browser}
                     onChange={(e) => setEv({ ...ev, browser: e.target.value })} />
              <label htmlFor="acr-ev-env">Environment</label>
              <input id="acr-ev-env" value={ev.environment}
                     onChange={(e) => setEv({ ...ev, environment: e.target.value })} />
            </>
          )}

          <label htmlFor="acr-ev-notes">Notes</label>
          <textarea id="acr-ev-notes" value={ev.notes}
                    onChange={(e) => setEv({ ...ev, notes: e.target.value })} />

          <button type="submit" disabled={busy}>Record evidence</button>
        </form>
      )}

      {/* ── the human decision ── */}
      <h4>Conformance decision</h4>
      {canEdit ? (
        <form onSubmit={(e) => { e.preventDefault(); act(() => decideAcrCriterion(reportId, criterionNum, status, remarks), `Recorded ${status}.`) }}>
          <fieldset>
            <legend>Final conformance level</legend>
            {FINAL_STATUSES.map((s) => {
              const allowed = permitted[s] !== false
              return (
                <div key={s}>
                  <input type="radio" id={`acr-status-${s}`} name="acr-status" value={s}
                         checked={status === s} disabled={!allowed}
                         onChange={() => setStatus(s)}
                         aria-describedby={allowed ? undefined : `acr-refusal-${s}`} />
                  <label htmlFor={`acr-status-${s}`}>{s}</label>
                  {!allowed && (
                    <p id={`acr-refusal-${s}`} className="acr-refusal">
                      Not available: {refusals[s]}
                    </p>
                  )}
                </div>
              )
            })}
          </fieldset>

          <label htmlFor="acr-remarks">
            Remarks and explanations
            {REMARKS_REQUIRED.includes(status) && <span aria-hidden="true"> *</span>}
            {REMARKS_REQUIRED.includes(status) && <span className="sr-only"> (required)</span>}
          </label>
          <textarea id="acr-remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)}
                    required={REMARKS_REQUIRED.includes(status)}
                    aria-describedby="acr-remarks-help" />
          <p id="acr-remarks-help" className="muted">
            {status === 'Partially Supports'
              ? 'Name what supports the criterion, what does not, the affected functionality, the user impact, any workaround, and the remediation plan.'
              : status === 'Does Not Support'
                ? 'Name the affected functionality and the known limitation.'
                : status === 'Not Applicable'
                  ? 'Explain why this criterion does not apply to the evaluated product or scope.'
                  : 'Optional for Supports — required for the other three.'}
          </p>

          <button type="submit" disabled={busy || !status}>Record decision</button>
        </form>
      ) : (
        <p className="muted">
          {criterion.final_status
            ? `${criterion.final_status}${criterion.remarks ? ` — ${criterion.remarks}` : ''}`
            : 'Not yet evaluated.'}
          <br />You do not have the editor role on this report.
        </p>
      )}

      <p className="muted">
        Evaluator: {criterion.evaluator || '—'} · Reviewer: {criterion.reviewer || '—'} ·
        Approval: {criterion.approval_state}
      </p>

      {canApprove && criterion.final_status && criterion.approval_state !== 'approved' && (
        <button type="button" disabled={busy}
                onClick={() => act(() => approveAcrCriterion(reportId, criterionNum), 'Criterion approved.')}>
          Approve this criterion
        </button>
      )}
    </section>
  )
}

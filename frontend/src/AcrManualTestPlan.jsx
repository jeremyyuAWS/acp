import { useEffect, useState } from 'react'
import { getCriterionPlans, startPlanRun, recordPlanStep, completePlanRun } from './acrApi'

/**
 * The guided manual test plan runner (PRD §14, Phase 3).
 *
 * WHY A GUIDED RUNNER RATHER THAN A NOTES BOX. Phase 1 let a tester attach a manual result with a
 * free-text method. That records that someone tested something; it does not record WHAT they did,
 * so a second person cannot reproduce it and a reviewer cannot tell a thorough keyboard sweep
 * from a glance. PRD §4.5 asks for reproducibility, and reproducibility means the steps.
 *
 * TWO RULES THIS SCREEN FOLLOWS, both learned earlier in this feature:
 *
 *   1. Every refusal sentence comes from the SERVER, rendered verbatim. The screen never decides
 *      for itself whether a run may be completed — `blocking_reason` is computed by acr_plans,
 *      the same module the publish gate consults. A screen that recomputed the rule is how you
 *      get a Complete button the server then rejects.
 *
 *   2. Which environment fields are required comes from the PLAN's own `needs`, not a list here.
 *      A screen-reader plan asks for the AT; a reflow plan does not. A second hardcoded list is
 *      how a field ends up optional on screen and mandatory at the gate.
 *
 * WHAT IT MUST NOT IMPLY. Completing a plan is not a pass. Every outcome — including `fail` —
 * finishes a step, because completeness is about whether the tester LOOKED. The server says so on
 * every response and this screen renders that sentence rather than paraphrasing it.
 */

const OUTCOME_LABEL = {
  pass: 'Passed',
  fail: 'Failed',
  blocked: 'Blocked — could not determine',
  not_applicable: 'Not applicable here',
}

export default function AcrManualTestPlan({ reportId, criterionNum, canEdit, onChange }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [openPlan, setOpenPlan] = useState(null)
  const [busy, setBusy] = useState(false)
  const [meta, setMeta] = useState({ tester: '', browser: '', assistive_tech: '', environment: '' })

  const load = () => getCriterionPlans(reportId, criterionNum)
    .then((d) => { setData(d); setError(null) })
    .catch((e) => setError(e.message))

  useEffect(() => { load() /* eslint-disable-next-line react-hooks/exhaustive-deps */ },
    [reportId, criterionNum])

  if (error) return <p role="alert">{error}</p>
  if (!data) return <p className="muted">Loading test plans…</p>

  const detailFor = (id) => (data.plan_detail || []).find((p) => p.plan_id === id)
  const runFor = (id) => (data.runs || []).find((r) => r.plan_id === id && !r.evidence_id)
  const doneFor = (id) => (data.runs || []).filter((r) => r.plan_id === id && r.evidence_id)

  const act = (fn) => {
    setBusy(true)
    return fn()
      .then(() => load())
      .then(() => { setError(null); onChange && onChange() })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false))
  }

  const start = (planId) => act(() => startPlanRun(reportId, criterionNum, planId))
  const step = (runId, index, outcome) => act(() => recordPlanStep(reportId, runId, index, outcome))
  const complete = (runId, result) => act(() => completePlanRun(reportId, runId, { result, ...meta }))

  return (
    <section aria-labelledby="acr-plans-heading">
      <h4 id="acr-plans-heading">Manual test plans</h4>

      {/* The whole point of the phase, stated where a tester reads it. */}
      <p className="muted">{data.note}</p>

      <p role="status" aria-live="polite">
        {data.complete
          ? 'Every manual test plan for this criterion is complete.'
          : `Manual evaluation is not finished: ${data.blocking_reason}`}
      </p>

      <ul className="acr-plan-list">
        {data.plans.map((p) => {
          const detail = detailFor(p.plan_id)
          const run = runFor(p.plan_id)
          const finished = doneFor(p.plan_id)
          const isOpen = openPlan === p.plan_id
          return (
            <li key={p.plan_id}>
              <h5>
                {p.title}
                {/* State, in words. Never colour alone — 1.4.1. */}
                <span className="acr-plan-state">
                  {' — '}
                  {p.complete ? 'complete'
                    : p.started ? `${p.answered_steps} of ${p.total_steps} steps recorded`
                      : 'not started'}
                </span>
              </h5>

              <button type="button" aria-expanded={isOpen}
                      onClick={() => setOpenPlan(isOpen ? null : p.plan_id)}>
                {isOpen ? 'Hide' : 'Show'} steps
                <span className="sr-only"> for {p.title}</span>
              </button>

              {!p.complete && p.blocking_reason && (
                <p className="muted">Outstanding: {p.blocking_reason}</p>
              )}

              {isOpen && detail && (
                <div>
                  <p><strong>Why this needs a person:</strong> {detail.why_manual}</p>

                  {detail.criteria_with_no_axe_rule.length > 0 && (
                    <p className="muted">
                      axe-core has no rule at all for{' '}
                      {detail.criteria_with_no_axe_rule.join(', ')} — automation has said nothing
                      about {detail.criteria_with_no_axe_rule.length === 1 ? 'it' : 'them'}.
                    </p>
                  )}

                  <h6>Before you start</h6>
                  <ul>{detail.preconditions.map((t) => <li key={t}>{t}</li>)}</ul>

                  <h6>Steps</h6>
                  <ol>
                    {detail.steps.map((s, i) => {
                      const recorded = run && run.steps ? run.steps[String(i)] : null
                      return (
                        <li key={s.action}>
                          <p>{s.action}</p>
                          <p className="muted"><strong>Expected:</strong> {s.expect}</p>
                          {recorded
                            ? <p>Recorded: {OUTCOME_LABEL[recorded] || recorded}</p>
                            : <p className="muted">No outcome recorded.</p>}
                          {canEdit && run && (
                            <div role="group"
                                 aria-label={`Outcome for step ${i + 1} of ${detail.title}`}>
                              {(data.step_outcomes || []).map((o) => (
                                <button key={o} type="button" disabled={busy}
                                        aria-pressed={recorded === o}
                                        onClick={() => step(run.id, i, o)}>
                                  {OUTCOME_LABEL[o] || o}
                                  <span className="sr-only"> for step {i + 1}</span>
                                </button>
                              ))}
                            </div>
                          )}
                        </li>
                      )
                    })}
                  </ol>

                  {canEdit && !run && (
                    <button type="button" disabled={busy} onClick={() => start(p.plan_id)}>
                      Start this plan
                      <span className="sr-only"> — {p.title}</span>
                    </button>
                  )}

                  {canEdit && run && (
                    <form onSubmit={(e) => { e.preventDefault(); complete(run.id, 'pass') }}>
                      <h6>Finish this run</h6>
                      {/* Required-ness comes from the plan's own `needs`. */}
                      <label htmlFor="acr-plan-tester">
                        Tester <span aria-hidden="true">*</span>
                        <span className="sr-only">(required)</span>
                      </label>
                      <input id="acr-plan-tester" required value={meta.tester}
                             onChange={(e) => setMeta({ ...meta, tester: e.target.value })} />

                      {detail.needs.map((f) => (
                        <span key={f}>
                          <label htmlFor={`acr-plan-${f}`}>
                            {f.replace(/_/g, ' ')} <span aria-hidden="true">*</span>
                            <span className="sr-only">(required by this plan)</span>
                          </label>
                          <input id={`acr-plan-${f}`} required value={meta[f] || ''}
                                 aria-describedby={`acr-plan-${f}-hint`}
                                 onChange={(e) => setMeta({ ...meta, [f]: e.target.value })} />
                          <span id={`acr-plan-${f}-hint`} className="muted">
                            Required before this run can be recorded as evidence.
                          </span>
                        </span>
                      ))}

                      <button type="submit" disabled={busy}>Record this run as evidence</button>
                    </form>
                  )}

                  {finished.length > 0 && (
                    <p className="muted">
                      {finished.length} completed run(s) recorded as evidence.
                    </p>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

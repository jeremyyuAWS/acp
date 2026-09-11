import { useEffect, useState } from 'react'
import { authEpoch } from './apiIdentity.js'
import { getRunInsights } from './remediationRunInsightsClient.js'
import './remediation-run-insights.css'
import DocumentWideAiOutcomes from './DocumentWideAiOutcomes.jsx'
import RemediationContribution from './RemediationContribution.jsx'

const rows = value => Array.isArray(value) ? value : []
const count = value => Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString() : 'Unavailable'
const purpose = value => ({ draft: 'First AI draft', fallback: 'Fallback draft', review: 'AI review', final_review: 'Final AI review' })[value] || 'Recorded attempt'
const display = value => value == null ? 'Unavailable' : typeof value === 'string' ? value : JSON.stringify(value, null, 2)

// Capitalizes whatever the backend actually recorded — never a hardcoded vendor dictionary. This
// renders only a real, recorded `ai_attempt_history.provider` value (the model that actually ran),
// so there is no vendor name to name in this file's own source for aiModel.test.js's "no rendered
// string names a model the product never calls" guard to catch; a static map here would be exactly
// the pattern that guard exists to flag, evidence-backed or not.
const providerLabel = value => (typeof value === 'string' && value ? value[0].toUpperCase() + value.slice(1).replaceAll('_', ' ') : 'Unknown provider')

// The concise line PRD §4 asks for: was AI used, by what, and what happened — read from SAVED
// records only (the same query `read_insights` already ran; no new AI request is made to answer
// this). Configuration alone ("cloud AI is selected") is never treated as evidence a model ran —
// this renders only what `activity_summary` (api/remediation_run_insights.py) actually counted.
function AiActivitySummary({ summary }) {
  if (!summary) return null
  if (summary.attempted === 0) {
    return <p className="ai-activity-summary"><strong>AI activity: </strong>{summary.not_used_reason || 'AI was not used for this run.'}</p>
  }
  return <div className="ai-activity-summary">
    <p><strong>AI activity</strong></p>
    <ul>
      {summary.by_model.map(row => <li key={`${row.provider}-${row.model}`}>
        {providerLabel(row.provider)} · {row.model}: {count(row.attempts)} request{row.attempts === 1 ? '' : 's'} attempted,{' '}
        {count(row.completed)} completed
      </li>)}
      <li>
        {count(summary.suggestions_generated)} suggestion{summary.suggestions_generated === 1 ? '' : 's'} generated
        {'; '}{count(summary.suggestions_applied)} applied
        {'; '}{count(summary.suggestions_needs_input)} need{summary.suggestions_needs_input === 1 ? 's' : ''} input
      </li>
      {summary.verified != null && <li>{count(summary.verified)} verified so far</li>}
    </ul>
  </div>
}

export default function RemediationRunInsights({ scanId, batchId, inlineDrilldown = false }) {
  const [open, setOpen] = useState(false)
  const [reload, setReload] = useState(0)
  const [state, setState] = useState(null)
  const [page, setPage] = useState(null)
  const identity = `${authEpoch()}:${scanId}:${batchId}`
  const offset = page?.identity === identity ? page.offset : 0
  useEffect(() => {
    if (!open || !scanId || !batchId) return
    const controller = new AbortController()
    let active = true
    setState(previous => ({ identity, loading: true, data: previous?.identity === identity ? previous.data : null }))
    getRunInsights(scanId, batchId, controller.signal, offset).then(data => {
      if (active) setState({ identity, data })
    }).catch(() => { if (active) setState(previous => ({ identity, error: true, data: previous?.identity === identity ? previous.data : null })) })
    return () => { active = false; controller.abort() }
  }, [open, identity, scanId, batchId, reload, offset])
  const current = state?.identity === identity ? state : null
  const data = current?.data
  return <details className="remediation-run-insights" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Saved model history, AI reviews and contribution</summary>
    {open && <>
      <p>Actual saved records for this remediation run. Viewing them makes no AI requests and approves no changes.</p>
      <button type="button" disabled={!scanId || !batchId || current?.loading} onClick={() => setReload(n => n + 1)}>Refresh saved history</button>
      {current?.error && data && <p role="alert">Refresh failed. Showing the last saved snapshot for this run.</p>}
      {current?.loading && data && <p role="status">Refreshing saved history; showing the last saved snapshot.</p>}
      {!scanId || !batchId ? <p>Select a remediation run.</p> : current?.error && !data ? <p role="alert">Saved history could not be loaded. Try refreshing.</p> : !current || (current.loading && !data) ? <p role="status">Loading saved model history…</p> : !data ? <p>Saved model history is unavailable in this environment.</p> : <>
        <p><strong>{data.standing_approval?.enabled ? 'Auto-approval on for this run' : 'Manual AI approval for this run'}</strong>. {data.standing_approval?.enabled ? 'The saved plan authorizes eligible suggestions, including fallbacks. Exceptions still need review; publishing stays separate.' : 'AI suggestions require your approval before application.'}</p>
        <AiActivitySummary summary={data.activity_summary} />
        <DocumentWideAiOutcomes snapshot={data.document_wide} />
        <RemediationContribution key={identity} snapshot={data.measured_contribution} inlineDrilldown={inlineDrilldown} />
        <h4>Saved suggestions by AI step</h4>
        <p>{data.contribution?.note || 'Proposal versions are not findings or verified fixes.'}</p>
        {data.coverage !== 'complete' && <p>History is partial. Counts include only retained records.</p>}
        <table><caption>Saved proposal versions in this run</caption><thead><tr><th>Source</th><th>Versions</th></tr></thead><tbody>
          {[['draft', 'First AI'], ['fallback', 'Next AI'], ['unattributed', 'Model linkage unavailable']].map(([key, label]) => <tr key={key}><th scope="row">{label}</th><td>{count(data.contribution?.[key])}</td></tr>)}
        </tbody></table>
        <h4>Measured contribution by finding</h4>
        {data.measured_contribution?.available ? <table><caption>Unique baseline findings with exact lineage</caption><thead><tr><th>AI step</th><th>Findings</th></tr></thead><tbody>
          <tr><th scope="row">First AI: suggestions ready</th><td>{count(data.measured_contribution.first_model_findings)}</td></tr>
          <tr><th scope="row">Next AI: additional suggestions</th><td>{count(data.measured_contribution.fallback_additional_findings)}</td></tr>
          {Object.hasOwn(data.measured_contribution, 'fallback_2_additional_findings') && <tr><th scope="row">Second fallback: additional suggestions</th><td>{count(data.measured_contribution.fallback_2_additional_findings)}</td></tr>}
          <tr><th scope="row">AI reviewer: checked suggestions</th><td>{count(data.measured_contribution.reviewed_findings)}</td></tr>
        </tbody></table> : <p>AI step contribution is not yet known for this run. Exact finding lineage is incomplete, so proposal versions are shown separately and are not counted as extra fixes.</p>}
        <p>These counts do not measure extra issues fixed. Exact proposal-version verification is {data.outcomes?.verified_fix_count == null ? 'not available yet' : 'reported separately'}.</p>
        <h4>What each model generated</h4>
        {rows(data.attempts).length === 0 && <p>No retained model attempts for this run. Older runs may not have recorded this history.</p>}
        {rows(data.attempts).map(attempt => <details key={attempt.attempt_id}>
          <summary>{purpose(attempt.purpose)} · {attempt.provider} · {attempt.model} · {attempt.file}</summary>
          <p>Recorded status: {String(attempt.status || 'unavailable').replaceAll('_', ' ')}</p>
          <p>Recorded at: {attempt.created_at || 'Unavailable'}</p>
          <pre>{attempt.output_retention === 'full' && typeof attempt.result?.text === 'string' ? attempt.result.text : 'Generated content unavailable or omitted by the retention limit.'}</pre>
          <p>Settled charge: {Number.isSafeInteger(attempt.actual_cost_units) ? `$${(attempt.actual_cost_units / 1000000).toFixed(6)} USD` : 'Unavailable'}. One call may cover several findings.</p>
        </details>)}
        <h4>AI review results</h4>
        {rows(data.review_receipts).length === 0 && <p>No retained AI reviews for this run.</p>}
        {rows(data.review_receipts).map((receipt, i) => <article key={`${receipt.operation_id}-${i}`}>
          <p><strong>{({ accept: 'AI reviewed', revise: 'Changes requested', unable: 'AI could not judge' })[receipt.review?.verdict] || 'Review result unavailable'}</strong> · {data.standing_approval?.enabled ? 'Eligible suggestions use the saved run authorization; exceptions need review' : 'Human approval still required'}</p>
          <p>{receipt.review?.reason}</p>
          <ol>{rows(receipt.review?.steps).map((step, j) => <li key={j}>{purpose(step.purpose)} · {step.provider || 'Provider unavailable'} · {step.model || 'Model unavailable'}: {step.reason}</li>)}</ol>
        </article>)}
        <h4>Saved proposal versions</h4>
        {rows(data.proposals).length === 0 && <p>No proposal snapshots have been recorded for this run.</p>}
        {rows(data.proposals).map(proposal => <details key={proposal.snapshot_id}>
          <summary>{proposal.file} · Rule {proposal.rule_id} · {proposal.created_at}</summary>
          <div className="run-insights-comparison"><div><h5>Original excerpt</h5><pre>{display(proposal.proposal?.before)}</pre></div><div><h5>Proposed change</h5><pre>{display(proposal.proposal?.proposed_value)}</pre></div></div>
          {rows(proposal.system_approvals).length > 0 && <p>Approved automatically by the system under the plan authorized by {data.standing_approval?.authorized_by || 'the run owner'}. This was not an individual human review.</p>}
          <p>{proposal.verification_reason}</p>
        </details>)}
        <h4>Estimated impact</h4>
        <p>{data.estimate?.available ? `Validated sample size: ${count(data.estimate.sample_size)}. This evidence applies only to its evaluated change type and model configuration.` : 'An estimate is not available until a complete, current evaluation covers this change type and model configuration.'}</p>
        {data.pagination && <nav aria-label="Model history pages">
          <button type="button" disabled={offset === 0} onClick={() => setPage({identity,offset:Math.max(0,offset - data.pagination.limit)})}>Previous records</button>
          <span> Record page {Math.floor(offset / data.pagination.limit) + 1} </span>
          <button type="button" disabled={!data.pagination.has_more} onClick={() => setPage({identity,offset:offset + data.pagination.limit})}>Next records</button>
        </nav>}
      </>}
    </>}
  </details>
}

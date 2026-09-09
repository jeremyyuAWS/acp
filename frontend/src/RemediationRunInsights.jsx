import { useEffect, useState } from 'react'
import { authEpoch } from './apiIdentity.js'
import { getRunInsights } from './remediationRunInsightsClient.js'
import './remediation-run-insights.css'

const rows = value => Array.isArray(value) ? value : []
const count = value => Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString() : 'Unavailable'
const purpose = value => ({ draft: 'First AI draft', fallback: 'Fallback draft', review: 'AI review', final_review: 'Final AI review' })[value] || 'Recorded attempt'
const display = value => value == null ? 'Unavailable' : typeof value === 'string' ? value : JSON.stringify(value, null, 2)

export default function RemediationRunInsights({ scanId, batchId }) {
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
    setState({ identity, loading: true })
    getRunInsights(scanId, batchId, controller.signal, offset).then(data => {
      if (active) setState({ identity, data })
    }).catch(() => { if (active) setState({ identity, error: true }) })
    return () => { active = false; controller.abort() }
  }, [open, identity, scanId, batchId, reload, offset])
  const current = state?.identity === identity ? state : null
  const data = current?.data
  return <details className="remediation-run-insights" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Saved model history, AI reviews and contribution</summary>
    {open && <>
      <p>Actual saved records for this remediation run. Viewing them makes no AI requests and approves no changes.</p>
      <button type="button" disabled={!scanId || !batchId || current?.loading} onClick={() => setReload(n => n + 1)}>Refresh saved history</button>
      {!scanId || !batchId ? <p>Select a remediation run.</p> : current?.error ? <p role="alert">Saved history could not be loaded. Try refreshing.</p> : !current || current.loading ? <p role="status">Loading saved model history…</p> : !data ? <p>Saved model history is unavailable in this environment.</p> : <>
        <h4>Saved suggestions by AI step</h4>
        <p>{data.contribution?.note || 'Proposal versions are not findings or verified fixes.'}</p>
        {data.coverage !== 'complete' && <p>History is partial. Counts include only retained records.</p>}
        <table><caption>Saved proposal versions in this run</caption><thead><tr><th>Source</th><th>Versions</th></tr></thead><tbody>
          {[['draft', 'First AI'], ['fallback', 'Next AI'], ['unattributed', 'Model linkage unavailable']].map(([key, label]) => <tr key={key}><th scope="row">{label}</th><td>{count(data.contribution?.[key])}</td></tr>)}
        </tbody></table>
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
          <p><strong>{({ accept: 'AI reviewed', revise: 'Changes requested', unable: 'AI could not judge' })[receipt.review?.verdict] || 'Review result unavailable'}</strong> · Human approval still required</p>
          <p>{receipt.review?.reason}</p>
          <ol>{rows(receipt.review?.steps).map((step, j) => <li key={j}>{purpose(step.purpose)} · {step.provider || 'Provider unavailable'} · {step.model || 'Model unavailable'}: {step.reason}</li>)}</ol>
        </article>)}
        <h4>Saved proposal versions</h4>
        {rows(data.proposals).length === 0 && <p>No proposal snapshots have been recorded for this run.</p>}
        {rows(data.proposals).map(proposal => <details key={proposal.snapshot_id}>
          <summary>{proposal.file} · Rule {proposal.rule_id} · {proposal.created_at}</summary>
          <div className="run-insights-comparison"><div><h5>Original excerpt</h5><pre>{display(proposal.proposal?.before)}</pre></div><div><h5>Proposed change</h5><pre>{display(proposal.proposal?.proposed_value)}</pre></div></div>
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

import RemediationThresholdDecision from './RemediationThresholdDecision.jsx'
import { useId, useState } from 'react'
import { authEpoch } from './apiIdentity.js'
import useRemediationAttemptStory from './useRemediationAttemptStory.js'
import { attemptPurpose, attemptStatus, attemptStory, reviewVerdict, fallbackEvidence, attemptReason } from './remediationAttemptStoryModel.js'
import './remediation-attempt-story.css'

const rows = value => Array.isArray(value) ? value : []
const money = value => Number.isSafeInteger(value) && value >= 0 ? `$${(value / 1000000).toFixed(6)} USD` : 'Charge unavailable'
const savedText = value => typeof value === 'string' ? value || 'Empty recorded value' : value == null ? 'Not retained' : JSON.stringify(value, null, 2)
const excerpt = value => typeof value === 'string' ? value.length > 180 ? `${value.slice(0, 180)}…` : value || 'Empty recorded value' : value == null ? 'Not retained' : 'Structured value · expand the full evidence to read it'
const date = value => Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString() : 'Time not recorded'
function Output({ attempt }) {
  return <details className="attempt-story-output"><summary>Read saved output</summary>
    <p>{attempt.output_retention === 'full' && typeof attempt.result?.text === 'string' ? attempt.result.text : 'Generated content was not retained or exceeded the retention limit.'}</p>
  </details>
}
function Attempt({ attempt, group }) {
  return <li className="attempt-story-step">
    <div className="attempt-story-step-heading"><strong>{attemptPurpose(attempt.purpose)}</strong><span>{date(attempt.created_at)}</span></div>
    <p className="attempt-story-model">{attempt.provider || 'Provider not recorded'} · {attempt.model || 'Model not recorded'}</p>
    <p>{attemptStatus(attempt.status)}</p>
    {typeof attempt.reason === 'string' && attempt.reason && <p><strong>Recorded reason:</strong> {attemptReason(attempt.reason)}</p>}
    {attempt.purpose === 'fallback' && <FallbackEvidence attempt={attempt} group={group} />}
    <p className="attempt-story-cost">Recorded charge: {money(attempt.actual_cost_units)}{attempt.spending_state ? ` · ${String(attempt.spending_state).replaceAll('_', ' ')}` : ''}. A call may cover multiple findings.</p>
    <Output attempt={attempt} />
  </li>
}
function FallbackEvidence({ attempt, group }) {
  const evidence = fallbackEvidence(group, attempt)
  return <details className="attempt-story-fallback"><summary>Fallback evidence · {evidence.earlierResult}</summary>
    <p><strong>Earlier recorded result:</strong> {evidence.earlierResult}{evidence.earlierReason ? ` · ${attemptReason(evidence.earlierReason)}` : ''}</p>
    <p>Why this fallback was requested is not recorded on this attempt. The earlier result is context, not a recorded fallback decision.</p>
    {evidence.comparable ? <p><strong>AI review comparison:</strong> {reviewVerdict(evidence.beforeReview.verdict)} → {reviewVerdict(evidence.afterReview.verdict)}. Both reviews identify their exact saved outputs.</p>
      : <p><strong>Improvement:</strong> Not measured. Comparable reviews of both outputs are not available in this page.</p>}
    {evidence.afterReview && <p><strong>Review of this fallback:</strong> {reviewVerdict(evidence.afterReview.verdict)}{evidence.afterReview.reason ? ` · ${attemptReason(evidence.afterReview.reason)}` : ''}</p>}
    <p>An AI review is not an independent accessibility check or human approval.</p>
  </details>
}
function ProposalPreview({ proposal }) {
  return <section className="attempt-story-preview" aria-label="Before and proposed change">
    <div className="attempt-story-preview-heading"><h5>Before → proposed</h5><span>Proposal only · not verified</span></div>
    <div className="attempt-story-comparison"><div><h5>Original excerpt</h5><p>{excerpt(proposal.proposal?.before)}</p></div><div><h5>Proposed change</h5><p>{excerpt(proposal.proposal?.proposed_value)}</p></div></div>
    <p className="attempt-story-checks">Exact-version checks: unavailable. {rows(proposal.validation_events).length > 0 ? `${proposal.validation_events.length} related check record(s) are available in the full evidence below.` : 'No related check records in this page.'}</p>
    <Proposal proposal={proposal} />
  </section>
}
function Proposal({ proposal }) {
  return <details className="attempt-story-proposal"><summary>Saved proposal · {proposal.rule_id ? `Rule ${proposal.rule_id}` : 'Rule not recorded'} · {date(proposal.created_at)}</summary>
    <div className="attempt-story-comparison"><div><h5>Original excerpt</h5><p>{savedText(proposal.proposal?.before)}</p></div><div><h5>Proposed change</h5><p>{savedText(proposal.proposal?.proposed_value)}</p></div></div>
    <p>{proposal.verification_reason || 'Exact verification of this proposal version is not recorded.'}</p>
    {rows(proposal.human_reviews).length > 0 && <><h5>Related human decisions</h5><ul>{proposal.human_reviews.map((event, index) => <li key={event.id || index}>{String(event.action || 'Decision recorded').replaceAll('_', ' ')} · {date(event.created_at)}</li>)}</ul><p>Related decisions do not establish that this exact proposal version was applied.</p></>}
    {rows(proposal.validation_events).length > 0 && <><h5>Related validation evidence</h5><ul>{proposal.validation_events.map((event, index) => <li key={event.id || index}>{String(event.outcome || 'Outcome recorded').replaceAll('_', ' ')} · {date(event.created_at)}{typeof event.detail === 'string' && <p>{event.detail}</p>}</li>)}</ul><p>These related events do not prove verification of this exact proposal version.</p></>}
  </details>
}

export default function RemediationAttemptStory({ scanId, batchId, live = false, paused = false, defaultOpen = false, reviewHref, modelFilter }) {
  const id = useId()
  const [open, setOpen] = useState(defaultOpen)
  const [choice, setChoice] = useState(null)
  const exactAttempts = Array.isArray(modelFilter?.attemptIds) ? modelFilter.attemptIds : null
  const filtering = exactAttempts !== null || typeof modelFilter?.provider === 'string' && typeof modelFilter?.model === 'string' && !!modelFilter.model
  const identity = JSON.stringify([authEpoch(), scanId, batchId, filtering ? modelFilter.provider : null, filtering ? modelFilter.model : null, exactAttempts])
  const current = choice?.identity === identity ? choice : { offset: 0 }
  const offset = current.offset || 0
  const { data, loading, error, receivedAt, refresh } = useRemediationAttemptStory({ scanId, batchId, live, paused, open, offset })
  // Filter whole, explicitly linked sequences rather than removing their predecessor evidence.
  const matches = group => !filtering || [...group.attempts, ...group.reviewAttempts].some(attempt => exactAttempts ? exactAttempts.includes(attempt.attempt_id) : attempt.provider === modelFilter.provider && attempt.model === modelFilter.model)
  const availableFiles = attemptStory(data).files.filter(name => !filtering || attemptStory(data, name, { live }).groups.some(matches))
  const file = availableFiles.includes(current.file) ? current.file : availableFiles[0] || ''
  const unfilteredStory = attemptStory(data, file, { live })
  const story = { ...unfilteredStory, groups: unfilteredStory.groups.filter(matches), unlinkedProposals: filtering ? [] : unfilteredStory.unlinkedProposals }
  const group = story.groups.find(item => item.key === current.operation) || story.groups[0]
  const proposal = group?.proposals.find(item => item.snapshot_id === current.proposal) || group?.proposals[0]
  const choose = changes => setChoice({ ...current, identity, ...changes })
  const limit = Number.isSafeInteger(data?.pagination?.limit) && data.pagination.limit > 0 ? data.pagination.limit : 100
  return <details className="attempt-story" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Follow an attempt <span>See what happened to a file, step by step</span></summary>
    {open && <div className="attempt-story-body">
      {filtering && <p className="attempt-story-model-context">Sequences for {modelFilter.provider && modelFilter.model ? `${modelFilter.provider} · ${modelFilter.model}` : 'the selected step'}. Linked steps from other models remain visible for context. This filter covers the current record page.</p>}
      <div className="attempt-story-toolbar"><p>Saved evidence only. Reading this story makes no AI calls.</p><button type="button" disabled={loading || !scanId || !batchId} onClick={refresh}>Refresh story</button></div>
      {error && <p role="status" className="attempt-story-notice">Refresh delayed.{data ? ' Showing the last saved page.' : ' The story could not be loaded.'}</p>}
      {!scanId || !batchId ? <p>Select a remediation run.</p> : !data && loading ? <p role="status">Loading saved attempts…</p> : !data ? <p>Saved attempts are unavailable for this run.</p> : <>
        <div className="attempt-story-selectors">
          <label htmlFor={`${id}-file`}>File in this record page<select id={`${id}-file`} value={file} disabled={!availableFiles.length} onChange={event => choose({ file: event.target.value, operation: null })}>
            {!availableFiles.length && <option value="">{filtering ? 'No matching files in this page' : 'No files in this page'}</option>}{availableFiles.map(name => <option key={name} value={name}>{name}</option>)}
          </select></label>
          {story.groups.length > 1 && <label htmlFor={`${id}-operation`}>Attempt sequence<select id={`${id}-operation`} value={group?.key || ''} onChange={event => choose({ operation: event.target.value })}>
            {story.groups.map((item, index) => <option key={item.key} value={item.key}>Sequence {index + 1} · {attemptPurpose(item.attempts[0].purpose)} · {date(item.attempts[0].created_at)}</option>)}
          </select></label>}
        </div>
        <p className="attempt-story-coverage">This page contains up to {limit} attempts, {limit} proposal snapshots, and {limit} AI reviews. A file’s sequence can continue on another page.{data.coverage !== 'complete' ? ' Some historical records are missing.' : ''}</p>
        {group ? <>
          <h4>{file}</h4>
          {group.proposals.length > 1 && <label className="attempt-story-version" htmlFor={`${id}-proposal`}>Saved proposal<select id={`${id}-proposal`} value={proposal?.snapshot_id || ''} onChange={event => choose({ proposal: event.target.value })}>
            {group.proposals.map((item, index) => <option key={item.snapshot_id} value={item.snapshot_id}>Proposal {index + 1} · {item.rule_id ? `Rule ${item.rule_id}` : 'Rule not recorded'} · {date(item.created_at)}</option>)}
          </select></label>}
          {proposal && <ProposalPreview proposal={proposal} />}
          <ol className="attempt-story-timeline">{group.attempts.map(attempt => <Attempt key={attempt.attempt_id} attempt={attempt} group={group} />)}
            {group.reviewAttempts.map(attempt => <Attempt key={attempt.attempt_id} attempt={attempt} group={group} />)}
          </ol>
          {group.receipts.map((receipt, index) => <section className="attempt-story-review" key={`${receipt.operation_id}:${receipt.proposal_sha256}:${index}`}>
            <RemediationThresholdDecision decision={receipt.review?.gate} />
            <h5>{reviewVerdict(receipt.review?.verdict)}</h5><p>{receipt.review?.reason ? attemptReason(receipt.review.reason) : 'No review explanation was retained.'}</p>
            <p>This review is linked to the saved output by its operation and content fingerprint. An AI review does not replace human approval.</p>
            <ul>{rows(receipt.review?.steps).map((step, i) => <li key={step.attempt_id || i}>{attemptPurpose(step.purpose)} · {step.provider || 'Provider not recorded'} · {step.model || 'Model not recorded'}: {attemptReason(step.reason)}</li>)}</ul>
          </section>)}
          <div className="attempt-story-next"><strong>Next action</strong><p>{group.next}</p>{reviewHref && <a href={reviewHref}>Open Review</a>}</div>
        </> : <p>{filtering ? 'No matching recorded attempts for this model on the current page. Other record pages may contain matching attempts.' : 'No linked model attempts for this file in the current page.'}</p>}
        {story.unlinkedProposals.length > 0 && <section><h4>Other saved proposals for this file</h4><p>Their model attempt is not linked in this page. No model attribution is inferred.</p>{story.unlinkedProposals.map(proposal => <Proposal key={proposal.snapshot_id} proposal={proposal} />)}</section>}
        <nav className="attempt-story-pages" aria-label="Attempt story record pages"><button type="button" disabled={offset === 0 || loading} onClick={() => choose({ offset: Math.max(0, offset - limit), operation: null })}>Previous records</button><span>Record page {Math.floor(offset / limit) + 1}</span><button type="button" disabled={!data.pagination?.has_more || loading} onClick={() => choose({ offset: offset + limit, operation: null })}>Next records</button></nav>
      </>}
      {receivedAt && <p className="attempt-story-updated">Last read {new Date(receivedAt).toLocaleTimeString()}{live && !paused ? ' · Refreshes while expanded and visible' : paused ? ' · Live updates paused' : ''}</p>}
    </div>}
  </details>
}

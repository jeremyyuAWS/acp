import { useId, useState } from 'react'
import { authEpoch } from './apiIdentity.js'
import useRemediationAttemptStory from './useRemediationAttemptStory.js'
import { attemptPurpose, attemptStatus, attemptStory, reviewVerdict } from './remediationAttemptStoryModel.js'
import './remediation-attempt-story.css'

const rows = value => Array.isArray(value) ? value : []
const money = value => Number.isSafeInteger(value) && value >= 0 ? `$${(value / 1000000).toFixed(6)} USD` : 'Charge unavailable'
const savedText = value => typeof value === 'string' ? value : value == null ? 'Not retained' : 'Structured content is available in the saved record.'
const date = value => Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString() : 'Time not recorded'
function Output({ attempt }) {
  return <details className="attempt-story-output"><summary>Read saved output</summary>
    <p>{attempt.output_retention === 'full' && typeof attempt.result?.text === 'string' ? attempt.result.text : 'Generated content was not retained or exceeded the retention limit.'}</p>
  </details>
}
function Attempt({ attempt }) {
  return <li className="attempt-story-step">
    <div className="attempt-story-step-heading"><strong>{attemptPurpose(attempt.purpose)}</strong><span>{date(attempt.created_at)}</span></div>
    <p className="attempt-story-model">{attempt.provider || 'Provider not recorded'} · {attempt.model || 'Model not recorded'}</p>
    <p>{attemptStatus(attempt.status)}</p>
    {typeof attempt.reason === 'string' && attempt.reason && <p><strong>Recorded reason:</strong> {attempt.reason.replaceAll('_', ' ')}</p>}
    {attempt.purpose === 'fallback' && !(typeof attempt.reason === 'string' && attempt.reason) && <p>Why this fallback was requested is not recorded on this attempt.</p>}
    <p className="attempt-story-cost">Recorded charge: {money(attempt.actual_cost_units)}{attempt.spending_state ? ` · ${String(attempt.spending_state).replaceAll('_', ' ')}` : ''}. A call may cover multiple findings.</p>
    <Output attempt={attempt} />
  </li>
}
function Proposal({ proposal }) {
  return <details className="attempt-story-proposal"><summary>Saved proposal · {proposal.rule_id ? `Rule ${proposal.rule_id}` : 'Rule not recorded'} · {date(proposal.created_at)}</summary>
    <div className="attempt-story-comparison"><div><h5>Original excerpt</h5><p>{savedText(proposal.proposal?.before)}</p></div><div><h5>Proposed change</h5><p>{savedText(proposal.proposal?.proposed_value)}</p></div></div>
    <p>{proposal.verification_reason || 'Exact verification of this proposal version is not recorded.'}</p>
    {rows(proposal.human_reviews).length > 0 && <><h5>Related human decisions</h5><ul>{proposal.human_reviews.map((event, index) => <li key={event.id || index}>{String(event.action || 'Decision recorded').replaceAll('_', ' ')} · {date(event.created_at)}</li>)}</ul><p>Related decisions do not establish that this exact proposal version was applied.</p></>}
    {rows(proposal.validation_events).length > 0 && <><h5>Related validation evidence</h5><ul>{proposal.validation_events.map((event, index) => <li key={event.id || index}>{String(event.outcome || 'Outcome recorded').replaceAll('_', ' ')} · {date(event.created_at)}{typeof event.detail === 'string' && <p>{event.detail}</p>}</li>)}</ul><p>These related events do not prove verification of this exact proposal version.</p></>}
  </details>
}

export default function RemediationAttemptStory({ scanId, batchId, live = false, paused = false, defaultOpen = false, reviewHref }) {
  const id = useId()
  const [open, setOpen] = useState(defaultOpen)
  const [choice, setChoice] = useState(null)
  const identity = `${authEpoch()}:${scanId}:${batchId}`
  const current = choice?.identity === identity ? choice : { offset: 0 }
  const offset = current.offset || 0
  const { data, loading, error, receivedAt, refresh } = useRemediationAttemptStory({ scanId, batchId, live, paused, open, offset })
  const availableFiles = attemptStory(data).files
  const file = availableFiles.includes(current.file) ? current.file : availableFiles[0] || ''
  const story = attemptStory(data, file, { live })
  const group = story.groups.find(item => item.key === current.operation) || story.groups[0]
  const choose = changes => setChoice({ ...current, identity, ...changes })
  const limit = Number.isSafeInteger(data?.pagination?.limit) && data.pagination.limit > 0 ? data.pagination.limit : 100
  return <details className="attempt-story" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Follow an attempt <span>See what happened to a file, step by step</span></summary>
    {open && <div className="attempt-story-body">
      <div className="attempt-story-toolbar"><p>Saved evidence only. Reading this story makes no AI calls.</p><button type="button" disabled={loading || !scanId || !batchId} onClick={refresh}>Refresh story</button></div>
      {error && <p role="status" className="attempt-story-notice">Refresh delayed.{data ? ' Showing the last saved page.' : ' The story could not be loaded.'}</p>}
      {!scanId || !batchId ? <p>Select a remediation run.</p> : !data && loading ? <p role="status">Loading saved attempts…</p> : !data ? <p>Saved attempts are unavailable for this run.</p> : <>
        <div className="attempt-story-selectors">
          <label htmlFor={`${id}-file`}>File in this record page<select id={`${id}-file`} value={file} disabled={!availableFiles.length} onChange={event => choose({ file: event.target.value, operation: null })}>
            {!availableFiles.length && <option value="">No files in this page</option>}{availableFiles.map(name => <option key={name} value={name}>{name}</option>)}
          </select></label>
          {story.groups.length > 1 && <label htmlFor={`${id}-operation`}>Attempt sequence<select id={`${id}-operation`} value={group?.key || ''} onChange={event => choose({ operation: event.target.value })}>
            {story.groups.map((item, index) => <option key={item.key} value={item.key}>Sequence {index + 1} · {attemptPurpose(item.attempts[0].purpose)} · {date(item.attempts[0].created_at)}</option>)}
          </select></label>}
        </div>
        <p className="attempt-story-coverage">This page contains up to {limit} attempts, {limit} proposal snapshots, and {limit} AI reviews. A file’s sequence can continue on another page.{data.coverage !== 'complete' ? ' Some historical records are missing.' : ''}</p>
        {group ? <>
          <h4>{file}</h4>
          <ol className="attempt-story-timeline">{group.attempts.map(attempt => <Attempt key={attempt.attempt_id} attempt={attempt} />)}
            {group.reviewAttempts.map(attempt => <Attempt key={attempt.attempt_id} attempt={attempt} />)}
          </ol>
          {group.receipts.map((receipt, index) => <section className="attempt-story-review" key={`${receipt.operation_id}:${receipt.proposal_sha256}:${index}`}>
            <h5>{reviewVerdict(receipt.review?.verdict)}</h5><p>{receipt.review?.reason || 'No review explanation was retained.'}</p>
            <p>This review is linked to the saved output by its operation and content fingerprint. An AI review does not replace human approval.</p>
            <ul>{rows(receipt.review?.steps).map((step, i) => <li key={step.attempt_id || i}>{attemptPurpose(step.purpose)} · {step.provider || 'Provider not recorded'} · {step.model || 'Model not recorded'}: {step.reason || 'Explanation not retained'}</li>)}</ul>
          </section>)}
          {group.proposals.map(proposal => <Proposal key={proposal.snapshot_id} proposal={proposal} />)}
          <div className="attempt-story-next"><strong>Next action</strong><p>{group.next}</p>{reviewHref && <a href={reviewHref}>Open Review</a>}</div>
        </> : <p>No linked model attempts for this file in the current page.</p>}
        {story.unlinkedProposals.length > 0 && <section><h4>Other saved proposals for this file</h4><p>Their model attempt is not linked in this page. No model attribution is inferred.</p>{story.unlinkedProposals.map(proposal => <Proposal key={proposal.snapshot_id} proposal={proposal} />)}</section>}
        <nav className="attempt-story-pages" aria-label="Attempt story record pages"><button type="button" disabled={offset === 0 || loading} onClick={() => choose({ offset: Math.max(0, offset - limit), operation: null })}>Previous records</button><span>Record page {Math.floor(offset / limit) + 1}</span><button type="button" disabled={!data.pagination?.has_more || loading} onClick={() => choose({ offset: offset + limit, operation: null })}>Next records</button></nav>
      </>}
      {receivedAt && <p className="attempt-story-updated">Last read {new Date(receivedAt).toLocaleTimeString()}{live && !paused ? ' · Refreshes while expanded and visible' : paused ? ' · Live updates paused' : ''}</p>}
    </div>}
  </details>
}

import { useEffect, useRef, useState } from 'react'
import { batchDecision, exclusionReason, proposalValues, selectionProblem, snapshotFinding } from './batchReviewSelection.js'
import LiveCounter from './LiveCounter.jsx'
import './batch-review-selection.css'

const PAGE_SIZE = 10
export default function BatchReviewSelection({ visible = [], decisions = {}, drafts = {}, scopeKey, scopeLabel = 'Current approval scope', onDecide, onResult, onBusy, onReviewExcluded, onShowAllReady, readyOutsideScope = 0, confirmRequest = 0, onConfirmRequestHandled, preparingProposals = false, onOpenPlan, disabled = false }) {
  const [entries, setEntries] = useState([])
  const [page, setPage] = useState(0)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState([])
  const [attempt, setAttempt] = useState(null)
  const [attemptResults, setAttemptResults] = useState([])
  const [announcement, setAnnouncement] = useState('')
  const attemptNumber = useRef(0)
  const lock = useRef(false)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const [groupBy, setGroupBy] = useState('file')
  const heading = useRef(null)
  const latest = useRef({ visible, decisions, drafts, scopeKey })
  latest.current = { visible, decisions, drafts, scopeKey }
  useEffect(() => { setEntries([]); setConfirming(false); setPage(0) }, [scopeKey])
  useEffect(() => { if (confirming) heading.current?.focus() }, [confirming])
  const findingCount = entries.reduce((n, e) => n + (e.finding._raw?.finding_count || 1), 0)
  const problems = entries.map(e => selectionProblem(e, visible, decisions, drafts))
  const successfulIds = new Set(results.filter(r => r.state === 'recorded').map(r => r.id))
  const uncertainIds = new Set(results.filter(r => r.state === 'uncertain').map(r => r.id))
  const selectable = f => !exclusionReason(f, decisions, drafts) && !successfulIds.has(f.id) && !uncertainIds.has(f.id)
  const eligible = visible.filter(selectable)
  const readyCount = eligible.reduce((n, f) => n + (f._raw?.finding_count || 1), 0)
  const shown = [...(confirming ? entries.map(e => e.finding) : eligible)].sort((a, b) =>
    String(groupBy === 'file' ? a.file : a.ruleId || a.rule_id || a.title).localeCompare(String(groupBy === 'file' ? b.file : b.ruleId || b.rule_id || b.title)))
  const pages = Math.max(1, Math.ceil(shown.length / PAGE_SIZE))
  const currentPage = Math.min(page, pages - 1)
  const pageItems = shown.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE)
  const exclusions = visible.reduce((out, f) => {
    const reason = exclusionReason(f, decisions, drafts)
      || (uncertainIds.has(f.id) ? 'Decision uncertain — refresh before retrying' : successfulIds.has(f.id) ? 'Approval recorded' : null)
    if (reason) out[reason] = (out[reason] || 0) + 1
    return out
  }, {})
  const confirmAllReady = () => {
    // This explicit action freezes the complete eligible scope, independent of inspection pages.
    // Reuse retained request identities on retries; never substitute a refreshed proposal.
    setEntries(eligible.map(f => entries.find(e => e.finding.id === f.id) || snapshotFinding(f)))
    setConfirming(true); setPage(0)
  }
  // A whole-run request freezes the eligible set immediately; later live updates never expand it.
  useEffect(() => { if (confirmRequest) { confirmAllReady(); onConfirmRequestHandled?.() } }, [confirmRequest])
  const toggle = f => {
    setConfirming(false)
    setEntries(old => old.some(e => e.finding.id === f.id) ? old.filter(e => e.finding.id !== f.id) : [...old, snapshotFinding(f)])
  }
  async function approve() {
    if (lock.current || disabled || !entries.length || problems.some(Boolean) || !onDecide) return
    lock.current = true; setBusy(true); onBusy?.(true)
    const batch = entries.slice(), initialScope = scopeKey, outcomes = []
    setAttempt({ scopeKey, number: ++attemptNumber.current, items: batch.length,
      proposals: batch.reduce((n, e) => n + proposalValues(e.finding).length, 0),
      files: new Set(batch.map(e => e.finding.file)).size })
    setAttemptResults([])
    setAnnouncement(`Recording approval for ${batch.length} review items.`)
    // Sequential writes bound pressure and permit a changed scope/source to stop unsent work.
    for (const entry of batch) {
      const current = latest.current
      const problem = !mounted.current || current.scopeKey !== initialScope ? 'Review scope changed' : selectionProblem(entry, current.visible, current.decisions, current.drafts)
      if (problem) { outcomes.push({ id: entry.finding.id, state: 'failed', message: problem }); setAttemptResults([...outcomes]); continue }
      try {
        await onDecide(entry.finding, batchDecision(entry))
        outcomes.push({ id: entry.finding.id, state: 'recorded' })
      } catch (error) {
        // Transport ambiguity must never turn into a fresh write with another request id.
        const uncertain = error?.changes === 'unknown' || error instanceof TypeError || !error?.status
          || (error.status >= 500 && error.changes !== 'none')
        outcomes.push({ id: entry.finding.id, state: uncertain ? 'uncertain' : 'failed', message: error?.message || 'Decision not confirmed' })
      }
      setAttemptResults([...outcomes])
      setResults(old => [...old.filter(r => !outcomes.some(o => o.id === r.id)), ...outcomes])
    }
    setResults(old => [...old.filter(r => !outcomes.some(o => o.id === r.id)), ...outcomes])
    setEntries(old => old.filter(e => !outcomes.some(r => r.id === e.finding.id && r.state !== 'failed')))
    setConfirming(false); setBusy(false); lock.current = false; onBusy?.(false)
    setAnnouncement(`Approval finished: ${outcomes.filter(r => r.state === 'recorded').length} approved, ${outcomes.filter(r => r.state === 'failed').length} failed, ${outcomes.filter(r => r.state === 'uncertain').length} uncertain. Writing and verification remain separate.`)
    onResult?.(outcomes)
  }
  const activeAttempt = attempt?.scopeKey === scopeKey ? attempt : null
  const summary = confirming && !busy ? { items: entries.length, proposals: entries.reduce((n, e) => n + proposalValues(e.finding).length, 0), files: new Set(entries.map(e => e.finding.file)).size } : activeAttempt
  const approved = attemptResults.filter(r => r.state === 'recorded').length
  const failed = attemptResults.filter(r => r.state === 'failed').length
  const uncertain = attemptResults.filter(r => r.state === 'uncertain').length
  return <section className="batch-review" aria-label="Select findings for approval">
    <h3 ref={heading} tabIndex={-1}>{busy ? 'Approving proposals' : confirming ? 'Confirm approval' : activeAttempt ? 'Approval results' : eligible.length ? 'Ready to approve' : preparingProposals ? 'Preparing proposals' : 'No proposals ready'}</h3>
    <p><b>Scope: {scopeLabel}</b></p>
    <p>Approve the ready proposals together, or inspect them and choose a subset. Writing and verification follow approval.</p>
    <p className="batch-sr-only" role="status" aria-live="polite" aria-atomic="true">{announcement}</p>
    {summary && <div className="batch-approval-summary" aria-label="Approval summary">
      <p><b>{summary.items} review item{summary.items === 1 ? '' : 's'} · {summary.proposals} proposal{summary.proposals === 1 ? '' : 's'} · {summary.files} file{summary.files === 1 ? '' : 's'}</b></p>
      {activeAttempt && (!confirming || busy) && <>
        <dl className="batch-approval-counts" aria-live="off">
          <div className="batch-approved"><dt>Approved</dt><dd><span aria-hidden="true"><LiveCounter key={attempt.number} value={approved} /></span><span className="batch-sr-only">{approved}</span></dd></div>
          <div><dt>Pending</dt><dd>{Math.max(0, attempt.items - attemptResults.length)}</dd></div>
          <div><dt>Failed</dt><dd>{failed}</dd></div>
          <div><dt>Uncertain</dt><dd>{uncertain}</dd></div>
        </dl>
        <p>Approved counts server-confirmed decisions. Writing and verification remain separate.</p>
      </>}
    </div>}
    {(eligible.length > 0 || entries.length > 0) && <div className="batch-review-sticky">
      <span><b>{entries.length > 0 ? `${findingCount} findings selected` : `${readyCount} findings ready`}</b> · {new Set((entries.length > 0 ? entries.map(e => e.finding) : eligible).map(f => f.file)).size} files</span>
      {confirming ? <><button type="button" disabled={busy} onClick={() => setConfirming(false)}>Back</button>
        <button type="button" className="primary" disabled={busy || disabled || problems.some(Boolean) || !entries.length || !onDecide} onClick={approve}>{busy ? 'Recording decisions…' : `Confirm approval of ${findingCount} findings`}</button></>
        : <>
          <button type="button" className="primary" disabled={busy || disabled || !eligible.length || !onDecide || problems.some(Boolean)} onClick={confirmAllReady}>Approve all ready ({readyCount})</button>
          {entries.length > 0 && <button type="button" disabled={busy || disabled || problems.some(Boolean) || !onDecide} onClick={() => { setConfirming(true); setPage(0) }}>Approve selected</button>}
        </>}
    </div>}
    {confirming && <p>Only these selected proposals will be approved. New proposals and excluded work are not included. Inspection is optional.</p>}
    {!eligible.length && !entries.length && !activeAttempt && <div role="status" className="batch-review-empty">
      <b>{preparingProposals ? 'Remediation is still processing this run.' : 'No proposals are ready for approval in this scope.'}</b>
      <p>{preparingProposals ? 'Readiness will update as processing finishes. You can approve ready proposals together without inspecting each item.' : visible.length
        ? Object.keys(exclusions).every(reason => reason.startsWith('Already') || reason === 'Approval recorded')
          ? 'These changes are already applied or approved. View their results and verification status; another proposal approval is not needed.'
          : Object.keys(exclusions).every(reason => reason === 'Manual work')
            ? 'These issues need your input in the source document. Open individual review for the required edits and instructions.'
            : 'Open individual review to inspect these issues and their available actions. See the status reasons below.'
        : 'There are no pending proposals in this scope. Choose another category to see completed changes, verification, or manual work.'}</p>
      {!preparingProposals && (exclusions['Version unavailable — review individually'] || exclusions['Missing proposal']) && <p>
        {exclusions['Version unavailable — review individually'] > 0 && <span>{exclusions['Version unavailable — review individually']} review {exclusions['Version unavailable — review individually'] === 1 ? 'item has' : 'items have'} no verifiable proposal version. </span>}
        {exclusions['Missing proposal'] > 0 && <span>{exclusions['Missing proposal']} review {exclusions['Missing proposal'] === 1 ? 'item has' : 'items have'} no complete proposal. </span>}
        Bulk approval requires valid proposals with recorded versions. Generating fresh proposals requires a separately approved run.
      </p>}
      {readyOutsideScope > 0 && onShowAllReady && <button type="button" className="primary" onClick={onShowAllReady}>Show all ready in this scan ({readyOutsideScope})</button>}
      {!preparingProposals && (exclusions['Version unavailable — review individually'] || exclusions['Missing proposal']) && onOpenPlan && <button type="button" onClick={onOpenPlan}>Open remediation plan</button>}
      {!preparingProposals && onReviewExcluded && <button type="button" onClick={onReviewExcluded}>Open individual review</button>}
    </div>}
    {(eligible.length > 0 || entries.length > 0) && <details className="batch-review-accounting">
      <summary>Approval details</summary>
      <p>{entries.length > 0
        ? <><b>{findingCount} findings selected</b> ({entries.length} review items) · {entries.reduce((n, e) => n + proposalValues(e.finding).length, 0)} proposals · {new Set(entries.map(e => e.finding.file)).size} files</>
        : <><b>{readyCount} findings ready</b> · {eligible.length} review items · {eligible.reduce((n, f) => n + proposalValues(f).length, 0)} proposals · {new Set(eligible.map(f => f.file)).size} files</>}</p>
    </details>}
    {Object.keys(exclusions).length > 0 && <details className="batch-review-exclusions">
      <summary>{Object.values(exclusions).reduce((a, b) => a + b, 0)} review items outside this approval</summary>
      <ul>{Object.entries(exclusions).map(([reason, count]) => <li key={reason}>{count} {reason.toLowerCase()}</li>)}</ul>
      <p>These items will not be approved by this action.</p>
    </details>}
    {problems.some(Boolean) && <p role="alert">Selection needs review: {problems.filter(Boolean).join(' · ')}. Clear affected selections and select the current proposals.</p>}
    {entries.length > 0 && <button type="button" disabled={busy} onClick={() => { setEntries([]); setConfirming(false) }}>Clear selection</button>}
    {shown.length > 0 && <details className="batch-review-inspection" key={confirming ? 'confirmation' : 'selection'}>
      <summary>{confirming ? 'Inspect selected proposals (optional)' : 'Inspect proposals or choose a subset (optional)'}</summary>
      <div className="batch-review-controls">
        <label>Group batch by <select value={groupBy} onChange={e => { setGroupBy(e.target.value); setPage(0) }}><option value="file">File</option><option value="change">Change type</option></select></label>
        {!confirming && <button type="button" disabled={busy || disabled} onClick={() => setEntries(eligible.map(f => entries.find(e => e.finding.id === f.id) || snapshotFinding(f)))}>Select all ready</button>}
      </div>
      <ol start={currentPage * PAGE_SIZE + 1}>
        {pageItems.map(f => {
          const entry = entries.find(e => e.finding.id === f.id)
          return <li key={f.id}>
            <label><input type="checkbox" checked={!!entry} disabled={busy || disabled || (!entry && !selectable(f))}
              onChange={() => toggle(f)} /> <strong>{f.file}</strong> · {f.ruleId || f.rule_id || f.title}</label>
            {proposalValues(f).map((value, i) => <details key={i}>
              <summary>Proposal {i + 1}: {String(value || 'Missing proposal').slice(0, 100)}{String(value || '').length > 100 ? '…' : ''}</summary>
              <dl><dt>Current value</dt><dd>{(f.proposals || f._raw?.proposals)?.[i]?.before || f.before || 'Not recorded'}</dd>
                <dt>Proposed value</dt><dd>{value || 'Missing proposal'}</dd></dl>
            </details>)}
          </li>
        })}
      </ol>
      {pages > 1 && <nav aria-label="Batch selection pages"><button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous batch page</button>
        <span>Page {currentPage + 1} of {pages} · {shown.length} review items</span>
        <button type="button" disabled={currentPage + 1 === pages} onClick={() => setPage(currentPage + 1)}>Next batch page</button></nav>}
    </details>}
    {results.some(r => r.state !== 'recorded') && <details className="batch-approval-errors">
      <summary>{results.filter(r => r.state !== 'recorded').length} review items need attention</summary>
      {results.filter(r => r.state !== 'recorded').map(r => <p key={r.id}>Finding {r.id}: {r.message}{r.state === 'uncertain' ? ' — refresh and check the recorded decision before retrying.' : ''}</p>)}
    </details>}
  </section>
}

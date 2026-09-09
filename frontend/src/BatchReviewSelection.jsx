import { useEffect, useRef, useState } from 'react'
import { batchDecision, exclusionReason, proposalValues, selectionProblem, snapshotFinding } from './batchReviewSelection.js'
import './batch-review-selection.css'

const PAGE_SIZE = 10
export default function BatchReviewSelection({ visible = [], decisions = {}, drafts = {}, scopeKey, onDecide, onResult, onBusy, disabled = false }) {
  const [entries, setEntries] = useState([])
  const [page, setPage] = useState(0)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState([])
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
  const shown = [...(confirming ? entries.map(e => e.finding) : visible)].sort((a, b) =>
    String(groupBy === 'file' ? a.file : a.ruleId || a.rule_id || a.title).localeCompare(String(groupBy === 'file' ? b.file : b.ruleId || b.rule_id || b.title)))
  const pages = Math.max(1, Math.ceil(shown.length / PAGE_SIZE))
  const currentPage = Math.min(page, pages - 1)
  const pageItems = shown.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE)
  const eligible = visible.filter(f => !exclusionReason(f, decisions, drafts))
  const exclusions = visible.reduce((out, f) => {
    const reason = exclusionReason(f, decisions, drafts)
    if (reason) out[reason] = (out[reason] || 0) + 1
    return out
  }, {})
  const successfulIds = new Set(results.filter(r => r.state === 'recorded').map(r => r.id))
  const uncertainIds = new Set(results.filter(r => r.state === 'uncertain').map(r => r.id))
  const selectable = f => !exclusionReason(f, decisions, drafts) && !successfulIds.has(f.id) && !uncertainIds.has(f.id)
  const toggle = f => {
    setConfirming(false)
    setEntries(old => old.some(e => e.finding.id === f.id) ? old.filter(e => e.finding.id !== f.id) : [...old, snapshotFinding(f)])
  }
  async function approve() {
    if (lock.current || disabled || !entries.length || problems.some(Boolean) || !onDecide) return
    lock.current = true; setBusy(true); onBusy?.(true)
    const batch = entries.slice(), initialScope = scopeKey, outcomes = []
    // Sequential writes bound pressure and permit a changed scope/source to stop unsent work.
    for (const entry of batch) {
      const current = latest.current
      const problem = !mounted.current || current.scopeKey !== initialScope ? 'Review scope changed' : selectionProblem(entry, current.visible, current.decisions, current.drafts)
      if (problem) { outcomes.push({ id: entry.finding.id, state: 'failed', message: problem }); continue }
      try {
        await onDecide(entry.finding, batchDecision(entry))
        outcomes.push({ id: entry.finding.id, state: 'recorded' })
      } catch (error) {
        // Transport ambiguity must never turn into a fresh write with another request id.
        const uncertain = error?.changes === 'unknown' || error instanceof TypeError || !error?.status
        outcomes.push({ id: entry.finding.id, state: uncertain ? 'uncertain' : 'failed', message: error?.message || 'Decision not confirmed' })
      }
      setResults(old => [...old.filter(r => !outcomes.some(o => o.id === r.id)), ...outcomes])
    }
    setResults(old => [...old.filter(r => !outcomes.some(o => o.id === r.id)), ...outcomes])
    setEntries(old => old.filter(e => !outcomes.some(r => r.id === e.finding.id && r.state !== 'failed')))
    setConfirming(false); setBusy(false); lock.current = false; onBusy?.(false)
    onResult?.(outcomes)
  }
  return <section className="batch-review" aria-label="Select findings for approval">
    <h3 ref={heading} tabIndex={-1}>{confirming ? 'Confirm selected proposals' : 'Select findings for approval'}</h3>
    <p>Select only proposals you have reviewed. Approval records your decision; writing and verification remain separate.</p>
    <div className="batch-review-controls">
      <label>Group batch by <select value={groupBy} onChange={e => { setGroupBy(e.target.value); setPage(0) }}><option value="file">File</option><option value="change">Change type</option></select></label>
      <button type="button" disabled={busy || disabled || confirming || !eligible.some(selectable)} onClick={() => setEntries(old => [...old, ...eligible.filter(f => selectable(f) && !old.some(e => e.finding.id === f.id)).map(snapshotFinding)])}>Select eligible in this view ({eligible.filter(selectable).length})</button>
      <button type="button" disabled={busy || !entries.length} onClick={() => { setEntries([]); setConfirming(false) }}>Clear selection</button>
    </div>
    <p>{Object.entries(exclusions).map(([reason, n]) => `${n} ${reason.toLowerCase()}`).join(' · ') || 'No ineligible findings in this view.'}</p>
    {problems.some(Boolean) && <p role="alert">Selection needs review: {problems.filter(Boolean).join(' · ')}. Clear affected selections and select the current proposals.</p>}
    <ol start={currentPage * PAGE_SIZE + 1}>
      {pageItems.map(f => {
        const entry = entries.find(e => e.finding.id === f.id)
        const reason = exclusionReason(f, decisions, drafts)
        return <li key={f.id}>
          <label><input type="checkbox" checked={!!entry} disabled={busy || disabled || (!entry && !selectable(f))}
            onChange={() => toggle(f)} /> <strong>{f.file}</strong> · {f.ruleId || f.rule_id || f.title}</label>
          {reason && <span className="muted"> · {reason}</span>}
          {proposalValues(f).map((value, i) => <details key={i} open={confirming || undefined}>
            <summary>Proposal {i + 1}: {String(value || 'Missing proposal').slice(0, 100)}{String(value || '').length > 100 ? '…' : ''}</summary>
            <dl><dt>Current value</dt><dd>{(f.proposals || f._raw?.proposals)?.[i]?.before || f.before || 'Not recorded'}</dd>
              <dt>Proposed value</dt><dd>{value || 'Missing proposal'}</dd></dl>
          </details>)}
        </li>
      })}
    </ol>
    {pages > 1 && <nav aria-label="Batch selection pages"><button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous batch page</button>
      <span>Page {currentPage + 1} of {pages} · {shown.length} findings</span>
      <button type="button" disabled={currentPage + 1 === pages} onClick={() => setPage(currentPage + 1)}>Next batch page</button></nav>}
    {results.length > 0 && <div role="status"><b>{results.filter(r => r.state === 'recorded').length} recorded · {results.filter(r => r.state === 'failed').length} not recorded · {results.filter(r => r.state === 'uncertain').length} uncertain</b>
      {results.filter(r => r.state !== 'recorded').map(r => <p key={r.id}>Finding {r.id}: {r.message}{r.state === 'uncertain' ? ' — refresh and check the recorded decision before retrying.' : ''}</p>)}
    </div>}
    <div className="batch-review-sticky">
      <span><b>{findingCount} findings selected</b> ({entries.length} review items) · {entries.reduce((n, e) => n + proposalValues(e.finding).length, 0)} proposals · {new Set(entries.map(e => e.finding.file)).size} files</span>
      {confirming ? <><button type="button" disabled={busy} onClick={() => setConfirming(false)}>Back to selection</button>
        <button type="button" className="primary" disabled={busy || disabled || problems.some(Boolean) || !entries.length} onClick={approve}>{busy ? 'Recording decisions…' : `Confirm approval of ${findingCount} findings`}</button></>
        : <button type="button" className="primary" disabled={busy || disabled || !entries.length || problems.some(Boolean) || !onDecide} onClick={() => { setConfirming(true); setPage(0) }}>Approve selected</button>}
    </div>
  </section>
}

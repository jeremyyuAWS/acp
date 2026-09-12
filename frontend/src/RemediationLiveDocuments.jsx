import './document-findings-table.css'
import RemediationCategoryPill, { categoryExplanation } from './RemediationCategoryPill.jsx'
import { createPortal } from 'react-dom'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import AssessWorklist from './AssessWorklist.jsx'
import SearchFilterBar, { useSearchFilter, matchesFilters } from './SearchFilterBar.jsx'
import RemediationFileDetail from './RemediationFileDetail.jsx'
import { documentRows } from './assessMetrics.js'
import { getFileRemediationDiffs, getScanRemediationDiffs } from './api.js'
import { remediationDiffPage } from './remediationCountSummary.js'
import ProgressQueueDrawer from './ProgressQueueDrawer.jsx'
import { PROGRESS_STATES } from './RemediationProgressSummary.jsx'
import RemediationProgressSummary from './RemediationProgressSummary.jsx'
import { liveDocumentCounts, materialKey, findingOutcomeTotals, recordedDocumentProgress, confirmedAssessmentBlock } from './remediationLiveDocumentState.js'
import './remediation-live-documents.css'
import { getFindingDispositions, listHitlQueue, getReleaseStatus, getSourceStatus } from './api.js'
import { changeCategory, categoryLabel } from './remediationCategories.js'

const OUTCOME_SHORT_LABELS = { automatic:'Auto', approval:'Approve', suggestion:'AI', manual:'Manual', unsupported:'No ACP', blocked:'Blocked', applied:'Pending', ai_applied:'AI applied', verified:'Verified', remaining:'Remaining', excluded:'Excluded', superseded:'Superseded', approved:'Approved · awaiting application' }
const OUTCOME_EXPLANATIONS = { remaining:'Findings without a verified fix that still need follow-up.', excluded:'Findings deliberately excluded from remediation.', superseded:'Older finding records replaced by a later recorded outcome.', approved:'Approved changes awaiting application. Approval alone does not mean the finding is fixed.' }

export default function RemediationLiveDocuments({ scanId, files, cap, assessment, fixes: suppliedFixes, fixTotal: suppliedTotal, refreshKey, snapshot, events = [], connected, progressDocuments, progressHostId = null, onShowDocuments }) {
  const search = useSearchFilter()
  const facets = [{ key: 'type', label: 'file type', get: row => row.file.split('.').pop().toUpperCase() }]
  const [progressHost, setProgressHost] = useState(null)
  useLayoutEffect(() => {
    const host = progressHostId ? document.getElementById(progressHostId) : null
    setProgressHost(host?.dataset.scanId === scanId && host?.dataset.batchId === snapshot?.batch_id ? host : null)
  }, [progressHostId, scanId, snapshot?.batch_id])
  const [progressFilter, setProgressFilter] = useState(null)
  const [queueSelection, setQueueSelection] = useState(null)
  const [coverageFilter, setCoverageFilter] = useState(null)
  const [outcomeFilter, setOutcomeFilter] = useState(null)
  const [scanEvidence, setScanEvidence] = useState(null)
  const [liveEvidence, setLiveEvidence] = useState(null)
  const [liveError, setLiveError] = useState(false)
  const [changed, setChanged] = useState([])
  const [announcement, setAnnouncement] = useState('')
  const signatures = useRef(null)
  const sourceRequest = useRef(null)
  const readSourceStatus = () => {
    const cached = sourceRequest.current
    if (cached?.scanId === scanId && (cached.pending || Date.now() - cached.completedAt < 30000)) return cached.promise
    const request = { scanId, pending: true, completedAt: 0 }
    request.promise = Promise.resolve().then(() => getSourceStatus(scanId)).catch(() => null).then(result => {
      request.pending = false; request.completedAt = Date.now(); return result
    })
    sourceRequest.current = request
    return request.promise
  }
  const liveMode = snapshot !== undefined || connected !== undefined
  const material = materialKey(scanId, snapshot, events)
  const [confirmedRefresh, setConfirmedRefresh] = useState(0)
  useEffect(() => {
    setQueueSelection(null); setLiveEvidence(null); setScanEvidence(null); setProgressFilter(null); setCoverageFilter(null); setOutcomeFilter(null); signatures.current = null; setChanged([]); setAnnouncement(''); search.clear()
  }, [scanId, snapshot?.batch_id])
  useEffect(() => {
    if (!liveMode || !scanId) return
    let current = true
    const timer = setTimeout(() => {
      Promise.allSettled([getFindingDispositions(scanId), listHitlQueue(scanId), getScanRemediationDiffs(scanId, true), Promise.resolve().then(() => getReleaseStatus(scanId)), readSourceStatus()]).then(results => {
        if (!current) return
        const [ledger, review, changes, release, source] = results
        setLiveEvidence(previous => ({ ...previous,
          ...(ledger.status === 'fulfilled' && (ledger.value?.available !== false || !previous?.ledger) ? { ledger: ledger.value } : {}),
          ...(review.status === 'fulfilled' ? { review: Array.isArray(review.value) ? review.value : [] } : {}),
          ...(release.status === 'fulfilled' ? { release: release.value } : {}),
          ...(source.status === 'fulfilled' ? { source: source.value } : {}),
        }))
        if (changes.status === 'fulfilled') setScanEvidence(remediationDiffPage(changes.value))
        else setScanEvidence(previous => previous || { items: [], total: null, error: true })
        setLiveError(ledger.status === 'fulfilled' && ledger.value?.available === false || results.slice(0, 3).some(result => result.status === 'rejected'))
        setConfirmedRefresh(n => n + 1)
      }).catch(() => { if (current) setLiveError(true) })
    }, 400)
    return () => { current = false; clearTimeout(timer) }
  }, [scanId, material, refreshKey, liveMode, connected])
  useEffect(() => {
    if (suppliedFixes !== undefined || liveMode) return
    let live = true
    setScanEvidence(null)
    if (scanId) Promise.resolve().then(() => getScanRemediationDiffs(scanId, true)).then(result => {
      if (live) setScanEvidence(remediationDiffPage(result))
    }).catch(() => { if (live) setScanEvidence({ items: [], total: null, error: true }) })
    return () => { live = false }
  }, [scanId, refreshKey, suppliedFixes === undefined, liveMode])
  const fixes = (liveMode && scanEvidence?.items) || suppliedFixes || scanEvidence?.items || []
  const fixTotal = (liveMode ? scanEvidence?.total : null) ?? suppliedTotal ?? scanEvidence?.total
  const opener = useRef(null)
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [retry, setRetry] = useState(0)
  useEffect(() => { if (!selected && opener.current?.isConnected) { opener.current.focus(); opener.current = null } }, [selected])
  const close = useCallback(() => setSelected(null), [])
  useEffect(() => {
    let current = true
    setDetail(null)
    if (!scanId || !selected) return
    getFileRemediationDiffs(scanId, selected).then(rows => {
      if (current) setDetail({ file: selected, rows: Array.isArray(rows) ? rows : [] })
    }).catch(() => { if (current) setDetail({ file: selected, rows: [], error: true }) })
    return () => { current = false }
  }, [scanId, selected, refreshKey, retry, confirmedRefresh])
  const fileNames = new Set(files.map(file => file.file))
  const scopedFixes = fixes.filter(fix => fileNames.has(fix.file))
  const loaded = selected ? scopedFixes.filter(row => row.file === selected) : []
  const rows = detail?.file === selected && detail.rows.length ? detail.rows : loaded
  const assessedFiles = [...files, ...(snapshot?.assessment_blocked_files || []).filter(blocked => !files.some(file => file.file === blocked.file)).map(blocked => ({ file:blocked.file, name:blocked.file, status:'error', assessment_blocked:true, assessment_blocked_reason:blocked.reason }))]
  const documentList = documentRows(assessedFiles, { cap, assessment }).map(row => {
    const blocked = confirmedAssessmentBlock(assessedFiles.find(file => file.file === row.file), snapshot)
    return blocked ? { ...row, assessmentBlocked:blocked, totalFindings:null, findings:null } : row
  })
  const currentDocuments = liveDocumentCounts(documentList, liveEvidence?.ledger, liveEvidence?.review, snapshot?.batch_id)
  const outcomeTotals = findingOutcomeTotals(currentDocuments || [])
  const recordedProgress = progressDocuments || documentList.map(row => {
    const confirmed = currentDocuments?.find(document => document.file === row.file && document.liveCounts)
    const file = files.find(file => file.file === row.file)
    return { file: row.file, progressState: recordedDocumentProgress(row, file, { confirmed, release: liveEvidence?.release, source: liveEvidence?.source, review: liveEvidence?.review, snapshot }) }
  })
  const effectiveProgress = documentList.map(row => row.assessmentBlocked
    ? {file:row.file,progressState:'attention'}
    : recordedProgress.find(document => document.file === row.file) || {file:row.file})
  const progressFiles = new Set(effectiveProgress.filter(document => !progressFilter || document.progressState === progressFilter).map(document => document.file))
  const fallbackFiles = progressFilter ? files.filter(file => progressFiles.has(file.file)) : files
  const displayedDocuments = currentDocuments || (liveMode || documentList.some(row => row.assessmentBlocked) ? documentList : null)
  const coverageEvidence = snapshot?.file_processing
  const affectedFiles = new Set((coverageEvidence?.files || []).filter(file => file.hasFindings).map(file => file.file))
  const finishedFiles = new Set((coverageEvidence?.attempts || []).filter(attempt => attempt.attempted && !attempt.retryScheduled && ['completed', 'failed', 'cancelled', 'skipped'].includes(attempt.state)).map(attempt => attempt.file))
  for (const attempt of coverageEvidence?.attempts || []) { if (attempt.retryScheduled || ['queued','processing','running','waiting','retrying'].includes(attempt.state)) finishedFiles.delete(attempt.file) }
  const searchScope = (displayedDocuments || []).filter(row => (!outcomeFilter || row.liveCounts?.[outcomeFilter] > 0) && (!progressFilter || effectiveProgress.some(document => document.file === row.file && document.progressState === progressFilter))
    && (!coverageFilter || affectedFiles.has(row.file) && (coverageFilter === 'withFindings' || (coverageFilter === 'processed' ? finishedFiles.has(row.file) : !finishedFiles.has(row.file)))))
  const visibleDocuments = searchScope.filter(matchesFilters(search, facets, row => row.file))
  const signature = JSON.stringify(currentDocuments?.map(r => [r.file, r.liveCounts, r.reconciliation]) || [])
  useEffect(() => {
    if (!currentDocuments) return
    const next = new Map(currentDocuments.map(r => [r.file, JSON.stringify(r.liveCounts)]))
    const updated = signatures.current ? [...next.keys()].filter(file => signatures.current.get(file) !== next.get(file)) : []
    signatures.current = next
    setChanged(updated)
    if (updated.length) setAnnouncement(`Finding categories updated for ${updated.length} document${updated.length === 1 ? '' : 's'}.`)
    const timer = setTimeout(() => setChanged([]), 1500)
    return () => clearTimeout(timer)
  }, [signature])
  const queueTitle = queueSelection?.kind === 'coverage'
    ? ({withFindings:'Files with findings',processed:'Files processed',remaining:'Files still to process'})[queueSelection.key]
    : queueSelection?.key ? PROGRESS_STATES.find(([key]) => key === queueSelection.key)?.[1] || 'Document progress' : 'All documents'
  const queueDocuments = documentList.filter(row => {
    if (!queueSelection) return false
    if (queueSelection.kind === 'coverage') return affectedFiles.has(row.file) && (queueSelection.key === 'withFindings' || (queueSelection.key === 'processed' ? finishedFiles.has(row.file) : !finishedFiles.has(row.file)))
    return !queueSelection.key || effectiveProgress.some(document => document.file === row.file && document.progressState === queueSelection.key)
  }).map(row => {
    const state = effectiveProgress.find(document => document.file === row.file)?.progressState
    return {file:row.file,status:row.assessmentBlocked ? 'blocked' : queueSelection?.kind === 'coverage' && queueSelection.key === 'processed' ? 'processed' : state,
      label:row.assessmentBlocked ? 'Blocked' : queueSelection?.kind === 'coverage' && queueSelection.key === 'processed' ? 'Processed' : PROGRESS_STATES.find(([key]) => key === state)?.[1], reason:row.assessmentBlocked?.reason, findingCount:row.totalFindings}
  })
  const progressSummary = <RemediationProgressSummary key={snapshot?.batch_id || scanId} animate={liveMode} documents={effectiveProgress} queueMode
    selected={queueSelection?.kind === 'document' ? queueSelection.key : undefined}
    coverage={coverageEvidence || { available: false }} selectedCoverage={queueSelection?.kind === 'coverage' ? queueSelection.key : undefined} baselineDocumentCounts={snapshot?.progress_baseline?.documents} startedAt={snapshot?.progress_baseline?.started_at}
    onCoverageSelect={selection => setQueueSelection({kind:'coverage',key:selection})}
    onSelect={selection => setQueueSelection({kind:'document',key:selection})} reconciling={liveError} />
  const selectedRow = documentList.find(row => row.file === selected)
  useEffect(() => { if (selectedRow?.assessmentBlocked) setSelected(null) }, [selectedRow?.assessmentBlocked?.reason, selected])
  const nextRow = documentList[documentList.findIndex(row => row.file === selected) + 1]
  useEffect(() => { setSelected(null) }, [scanId])
  return <div className="remediation-live-documents">
    {queueSelection && <ProgressQueueDrawer title={queueTitle} scopeLabel={`${documentList.length} assessment documents`}
      files={queueDocuments} error={queueSelection.kind === 'coverage' && !coverageEvidence?.available ? 'Recorded file processing coverage is unavailable for this run.' : undefined}
      onClose={() => setQueueSelection(null)} onOpenFile={row => { setQueueSelection(null); setSelected(row.file) }}/>}
    <div hidden={!!selectedRow && !selectedRow.assessmentBlocked}>
    {progressHost?.isConnected && progressHost.dataset.batchId === snapshot?.batch_id
      ? createPortal(progressSummary, progressHost) : progressSummary}
    <p className="vh" role="status" aria-live="polite">{announcement}</p>
    {liveError && <p role="status">Live categories could not refresh. The last confirmed counts remain visible.</p>}
    {liveMode && !currentDocuments && documentList.some(row => !row.assessmentBlocked) && <p className="muted">Current finding outcomes are reconciling. Assessment counts remain visible below.</p>}
    <p className="muted">{currentDocuments ? "Open a document to inspect its findings and saved changes." : "Assessment findings stay visible below. Applied-change records remain separate from finding counts."}</p>
    {displayedDocuments ? <section aria-label="Documents"><h3>Documents <small>· {displayedDocuments.length}</small></h3>
      {displayedDocuments.some(row => row.reconciliation) && <p role="status">{displayedDocuments.filter(row => row.reconciliation).length} documents have finding counts reconciling. Their outcomes are not included in live totals.</p>}
      <p className="muted">Each reconciled finding appears once. Counts update after saved results arrive{connected === false ? ' · reconnecting to live updates' : ''}.</p>
      <div className="live-document-categories live-finding-filters" aria-label="Live finding outcomes">
        <button type="button" className="live-finding-filter live-finding-filter--all" aria-pressed={!outcomeFilter} onClick={() => setOutcomeFilter(null)}>All findings</button>
        {Object.entries(outcomeTotals).map(([category, count]) => <button type="button" key={category}
          className={`live-finding-filter remediation-category-pill--${category}`}
          aria-label={`${OUTCOME_SHORT_LABELS[category] || categoryLabel(category)}: ${count} findings`}
          title={OUTCOME_EXPLANATIONS[category] || categoryExplanation(category)}
          aria-pressed={outcomeFilter === category} onClick={() => setOutcomeFilter(category)}>
          {OUTCOME_SHORT_LABELS[category] || categoryLabel(category)} <strong>{count}</strong>
        </button>)}
      </div>
      <p className="muted">{visibleDocuments.length} of {displayedDocuments.length} documents shown · outcome counts cover reconciled documents in this view.</p>
      <SearchFilterBar ctl={search} items={searchScope} facets={facets} noun="documents" />
      <div className="document-findings-scroll document-findings-scroll-all" role="region" aria-label="Document findings table" tabIndex={0}><table className="live-document-table document-findings-table"><thead><tr><th scope="col">Document</th><th scope="col" className="findings-criteria-heading">WCAG criteria <br />with issues</th><th scope="col" className="findings-total-heading">Total <br />findings</th><th scope="col">Remediation categories</th><th scope="col"><span className="vh">Details</span></th></tr></thead>
        <tbody>{visibleDocuments.map(row => <tr key={row.file} className={changed.includes(row.file) ? 'live-document-changed' : undefined}>
          <th scope="row">{row.file}</th><td className="col-criteria">{row.findings ? new Set(row.findings.map(f => f.sc)).size : '—'}</td><td className="col-findings">{row.totalFindings ?? '—'}</td><td>{row.assessmentBlocked ? <div className="assessment-blocked-document" role="status"><strong>Blocked</strong><span>{row.assessmentBlocked.reason}</span><small>No assessment finding count is available. Resolve the assessment issue before remediation.</small></div> : <>{row.reconciliation && <span role="status">Reconciling · {row.reconciliation.recorded} recorded / {row.reconciliation.expected ?? "unknown"} assessed. {row.reconciliation.reason}</span>}<div className="live-document-categories">{!row.liveCounts && <span className="muted">Awaiting recorded outcomes</span>}{Object.entries(row.liveCounts || {}).map(([category, count]) =>
            ['remaining','excluded','superseded','approved'].includes(category) ? <span key={category}>{({ remaining:'Remaining', excluded:'Excluded', superseded:'Superseded', approved:'Approved · awaiting application' })[category]} <strong>{count}</strong></span>
            : <RemediationCategoryPill key={category} category={category} count={count} />)}</div></>}</td>
          <td>{row.assessmentBlocked ? <span className="muted">Assessment blocked</span> : <button type="button" className="ghost small" onClick={() => { opener.current = document.activeElement; setSelected(row.file) }}>View fixes</button>}</td>
        </tr>)}</tbody>
      </table></div>
    </section> : <AssessWorklist changeRows={scopedFixes.map(fix => ({ ...fix, category: changeCategory(fix) }))} files={fallbackFiles} cap={cap} assessment={assessment} initialFilter="all" openLabel="View fixes"
      renderProgress={row => {
        return <span>{['applied', 'ai_applied', 'verified'].map(category => {
          const count = scopedFixes.filter(fix => fix.file === row.file && changeCategory(fix) === category).length
          return count > 0 && <RemediationCategoryPill key={category} category={category} count={count} unit="records" />
        })}</span>
      }} onOpenFile={row => { opener.current = document.activeElement; setSelected(row.file) }} />}
    {suppliedFixes === undefined && !scanEvidence && <p role="status">Loading recorded changes…</p>}
    {scanEvidence?.error && <p role="status">Recorded changes could not be loaded. Open a file to retry its evidence.</p>}
    <p className="muted">{scopedFixes.length} applied-change records loaded for these documents{fixTotal != null ? ` · ${fixTotal} across the run` : ' · run total unavailable'}. Loaded counts may be partial; opening a file loads its evidence.</p>
    </div>
    {selectedRow && !selectedRow.assessmentBlocked && <RemediationFileDetail row={selectedRow} changes={rows} loading={!detail}
      unavailable={!!detail && !detail.rows.length} onRetry={() => setRetry(n => n + 1)} onBack={close}
      nextName={nextRow?.file} onNext={nextRow ? () => setSelected(nextRow.file) : undefined} />}
  </div>
}

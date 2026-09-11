import RemediationCategoryPill from './RemediationCategoryPill.jsx'
import { useCallback, useEffect, useRef, useState } from 'react'
import AssessWorklist from './AssessWorklist.jsx'
import RemediationFileDetail from './RemediationFileDetail.jsx'
import { documentRows } from './assessMetrics.js'
import { getFileRemediationDiffs, getScanRemediationDiffs } from './api.js'
import { remediationDiffPage } from './remediationCountSummary.js'
import { liveDocumentCounts, materialKey } from './remediationLiveDocumentState.js'
import './remediation-live-documents.css'
import { getFindingDispositions, listHitlQueue } from './api.js'
import { changeCategory } from './remediationCategories.js'

export default function RemediationLiveDocuments({ scanId, files, cap, assessment, fixes: suppliedFixes, fixTotal: suppliedTotal, refreshKey, snapshot, events = [], connected }) {
  const [scanEvidence, setScanEvidence] = useState(null)
  const [liveEvidence, setLiveEvidence] = useState(null)
  const [liveError, setLiveError] = useState(false)
  const [changed, setChanged] = useState([])
  const [announcement, setAnnouncement] = useState('')
  const signatures = useRef(null)
  const liveMode = snapshot !== undefined || connected !== undefined
  const material = materialKey(scanId, snapshot, events)
  const [confirmedRefresh, setConfirmedRefresh] = useState(0)
  useEffect(() => {
    setLiveEvidence(null); setScanEvidence(null); signatures.current = null; setChanged([]); setAnnouncement('')
  }, [scanId, snapshot?.batch_id])
  useEffect(() => {
    if (!liveMode || !scanId) return
    let current = true
    const timer = setTimeout(() => {
      Promise.all([getFindingDispositions(scanId), listHitlQueue(scanId), getScanRemediationDiffs(scanId, true)]).then(([ledger, review, changes]) => {
        if (!current) return
        setLiveEvidence({ ledger, review: Array.isArray(review) ? review : [] })
        setScanEvidence(remediationDiffPage(changes)); setLiveError(false)
        setConfirmedRefresh(n => n + 1)
      }).catch(() => { if (current) setLiveError(true) })
    }, 400)
    return () => { current = false; clearTimeout(timer) }
  }, [scanId, material, refreshKey, liveMode])
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
  const documentList = documentRows(files, { cap, assessment })
  const currentDocuments = liveDocumentCounts(documentList, liveEvidence?.ledger, liveEvidence?.review, snapshot?.batch_id)
  const signature = JSON.stringify(currentDocuments?.map(r => [r.file, r.liveCounts]) || [])
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
  const selectedRow = documentList.find(row => row.file === selected)
  const nextRow = documentList[documentList.findIndex(row => row.file === selected) + 1]
  useEffect(() => { setSelected(null) }, [scanId])
  return <div className="remediation-live-documents">
    <div hidden={!!selectedRow}>
    <p className="vh" role="status" aria-live="polite">{announcement}</p>
    {liveError && <p role="status">Live categories could not refresh. The last confirmed counts remain visible.</p>}
    {liveMode && !currentDocuments && <p className="muted">Current finding outcomes are reconciling. Assessment counts remain visible below.</p>}
    <p className="muted">{currentDocuments ? "Open a document to inspect its findings and saved changes." : "Assessment findings stay visible below. Applied-change records remain separate from finding counts."}</p>
    {currentDocuments ? <section aria-label="Documents"><h3>Documents <small>· {currentDocuments.length}</small></h3>
      <p className="muted">Each finding appears once. Counts update after saved results arrive{connected === false ? ' · reconnecting to live updates' : ''}.</p>
      <table className="live-document-table"><thead><tr><th scope="col">Document</th><th scope="col">WCAG criteria with issues</th><th scope="col">Total findings</th><th scope="col">Remediation categories</th><th scope="col"><span className="vh">Details</span></th></tr></thead>
        <tbody>{currentDocuments.map(row => <tr key={row.file} className={changed.includes(row.file) ? 'live-document-changed' : undefined}>
          <th scope="row">{row.file}</th><td>{new Set(row.findings.map(f => f.sc)).size}</td><td>{row.totalFindings}</td><td><div className="live-document-categories">{Object.entries(row.liveCounts).map(([category, count]) =>
            ['remaining','excluded','superseded','approved'].includes(category) ? <span key={category}>{({ remaining:'Remaining', excluded:'Excluded', superseded:'Superseded', approved:'Approved · awaiting application' })[category]} <strong>{count}</strong></span>
            : <RemediationCategoryPill key={category} category={category} count={count} />)}</div></td>
          <td><button type="button" onClick={() => { opener.current = document.activeElement; setSelected(row.file) }}>View fixes</button></td>
        </tr>)}</tbody>
      </table>
    </section> : <AssessWorklist changeRows={scopedFixes.map(fix => ({ ...fix, category: changeCategory(fix) }))} files={files} cap={cap} assessment={assessment} initialFilter="all" openLabel="View fixes"
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
    {selectedRow && <RemediationFileDetail row={selectedRow} changes={rows} loading={!detail}
      unavailable={!!detail && !detail.rows.length} onRetry={() => setRetry(n => n + 1)} onBack={close}
      nextName={nextRow?.file} onNext={nextRow ? () => setSelected(nextRow.file) : undefined} />}
  </div>
}

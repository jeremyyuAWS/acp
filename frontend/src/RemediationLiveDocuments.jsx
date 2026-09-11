import RemediationCategoryPill from './RemediationCategoryPill.jsx'
import { useCallback, useEffect, useRef, useState } from 'react'
import AssessWorklist from './AssessWorklist.jsx'
import RemediationFileDetail from './RemediationFileDetail.jsx'
import { documentRows } from './assessMetrics.js'
import { getFileRemediationDiffs, getScanRemediationDiffs } from './api.js'
import { remediationDiffPage } from './remediationCountSummary.js'
import { changeCategory } from './remediationCategories.js'

export default function RemediationLiveDocuments({ scanId, files, cap, assessment, fixes: suppliedFixes, fixTotal: suppliedTotal, refreshKey }) {
  const [scanEvidence, setScanEvidence] = useState(null)
  useEffect(() => {
    if (suppliedFixes !== undefined) return
    let live = true
    setScanEvidence(null)
    if (scanId) Promise.resolve().then(() => getScanRemediationDiffs(scanId, true)).then(result => {
      if (live) setScanEvidence(remediationDiffPage(result))
    }).catch(() => { if (live) setScanEvidence({ items: [], total: null, error: true }) })
    return () => { live = false }
  }, [scanId, refreshKey, suppliedFixes === undefined])
  const fixes = suppliedFixes || scanEvidence?.items || []
  const fixTotal = suppliedTotal ?? scanEvidence?.total
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
  }, [scanId, selected, refreshKey, retry])
  const fileNames = new Set(files.map(file => file.file))
  const scopedFixes = fixes.filter(fix => fileNames.has(fix.file))
  const loaded = selected ? scopedFixes.filter(row => row.file === selected) : []
  const rows = detail?.file === selected && detail.rows.length ? detail.rows : loaded
  const documentList = documentRows(files, { cap, assessment })
  const selectedRow = documentList.find(row => row.file === selected)
  const nextRow = documentList[documentList.findIndex(row => row.file === selected) + 1]
  useEffect(() => { setSelected(null) }, [scanId])
  return <div className="remediation-live-documents">
    <div hidden={!!selectedRow}>
    <p className="muted">Assessment findings stay visible below. The Remediation category column shows applied-change records as they arrive; open a file for changes by WCAG success criterion.</p>
    <AssessWorklist changeRows={scopedFixes.map(fix => ({ ...fix, category: changeCategory(fix) }))} files={files} cap={cap} assessment={assessment} initialFilter="all" openLabel="View fixes"
      renderProgress={row => {
        return <span>{['applied', 'ai_applied', 'verified'].map(category => {
          const count = scopedFixes.filter(fix => fix.file === row.file && changeCategory(fix) === category).length
          return count > 0 && <RemediationCategoryPill key={category} category={category} count={count} unit="records" />
        })}</span>
      }} onOpenFile={row => { opener.current = document.activeElement; setSelected(row.file) }} />
    {suppliedFixes === undefined && !scanEvidence && <p role="status">Loading recorded changes…</p>}
    {scanEvidence?.error && <p role="status">Recorded changes could not be loaded. Open a file to retry its evidence.</p>}
    <p className="muted">{scopedFixes.length} applied-change records loaded for these documents{fixTotal != null ? ` · ${fixTotal} across the run` : ' · run total unavailable'}. Loaded counts may be partial; opening a file loads its evidence.</p>
    </div>
    {selectedRow && <RemediationFileDetail row={selectedRow} changes={rows} loading={!detail}
      unavailable={!!detail && !detail.rows.length} onRetry={() => setRetry(n => n + 1)} onBack={close}
      nextName={nextRow?.file} onNext={nextRow ? () => setSelected(nextRow.file) : undefined} />}
  </div>
}

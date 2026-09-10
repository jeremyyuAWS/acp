import { useCallback, useEffect, useState } from 'react'
import AssessWorklist from './AssessWorklist.jsx'
import Drawer from './Drawer.jsx'
import { getFileRemediationDiffs, getScanRemediationDiffs } from './api.js'
import { remediationDiffPage } from './remediationCountSummary.js'
import { categoryLabel } from './remediationCategories.js'
import { scOf, groupMetaForSc } from './fixSummary.js'

const valueText = value => value == null ? 'Not recorded' : typeof value === 'string' ? value : JSON.stringify(value, null, 2)

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
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [retry, setRetry] = useState(0)
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
  const counts = scopedFixes.reduce((result, fix) => { result.set(fix.file, (result.get(fix.file) || 0) + 1); return result }, new Map())
  const loaded = selected ? scopedFixes.filter(row => row.file === selected) : []
  const rows = detail?.file === selected && detail.rows.length ? detail.rows : loaded
  const groups = rows.reduce((result, row) => {
    const sc = scOf(row.rule_id || row.sc || row.wcag) || 'Not recorded'
    ;(result[sc] ||= []).push(row)
    return result
  }, {})
  return <div className="remediation-live-documents">
    <p className="muted">Assessment findings stay visible below. The Remediation category column shows applied-change records as they arrive; open a file for changes by WCAG success criterion.</p>
    <AssessWorklist changeRows={scopedFixes.map(fix => ({ ...fix, category: fix.verified === true ? 'verified' : 'applied' }))} files={files} cap={cap} assessment={assessment} initialFilter="all" openLabel="View fixes"
      renderProgress={row => {
        const count = (counts.get(row.file) || 0)
        return <div>{count > 0 && <details><summary>Applied changes · {count} records</summary>
          <ul>{scopedFixes.filter(fix => fix.file === row.file).map((fix, index) => <li key={index}>
            SC {scOf(fix.rule_id || fix.sc || fix.wcag)} · {categoryLabel(fix.verified === true ? 'verified' : 'applied')}
          </li>)}</ul><small>{count} applied change{count === 1 ? '' : 's'} loaded</small>
        </details>}</div>
      }} onOpenFile={row => setSelected(row.file)} />
    {suppliedFixes === undefined && !scanEvidence && <p role="status">Loading recorded changes…</p>}
    {scanEvidence?.error && <p role="status">Recorded changes could not be loaded. Open a file to retry its evidence.</p>}
    <p className="muted">{scopedFixes.length} applied-change records loaded for these documents{fixTotal != null ? ` · ${fixTotal} across the run` : ' · run total unavailable'}. Loaded counts may be partial; opening a file loads its evidence.</p>
    {selected && <Drawer title={selected} subtitle="Remediation details by WCAG success criterion" onClose={close}>
      {!detail && <p role="status">Loading file evidence…</p>}
      {detail && !detail.rows.length && <p role="status">No additional file evidence is available. This does not establish that the file has no fixes. <button type="button" onClick={() => setRetry(n => n + 1)}>Refresh evidence</button></p>}
      {rows.length > 0 && <p>{rows.length} recorded changes · {Object.keys(groups).length} success criteria. Applied changes do not establish that the whole document is accessible.</p>}
      {Object.entries(groups).map(([sc, changes]) => <details key={sc} className="remediation-fix-detail">
        <summary>SC {sc} · {groupMetaForSc(sc).category} · {changes.length} change{changes.length === 1 ? '' : 's'}</summary>
        {changes.map((change, index) => <article key={change.id || index} className="remediation-fix-detail">
          <h3>Change {index + 1}{change.page != null ? ` · Page ${change.page}` : ''}</h3>
          <dl><dt>Before</dt><dd>{valueText(change.before)}</dd><dt>After</dt><dd>{valueText(change.after ?? change.value ?? change.approved_value)}</dd></dl>
          <p>Verification: {change.verified === true || change.validated === true ? 'Verified' : 'Not reported in this record'}</p>
          {change.reason && <p>{valueText(change.reason)}</p>}
        </article>)}
      </details>)}
    </Drawer>}
  </div>
}

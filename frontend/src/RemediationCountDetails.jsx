import './remediation-evidence.css'
import { useEffect, useState } from 'react'
import Drawer from './Drawer.jsx'
import { listHitlQueue, getScanRemediationDiffs } from './api.js'
import { remediationDiffPage } from './remediationCountSummary.js'
import { scOf } from './fixSummary.js'
import { authEpoch } from './apiIdentity.js'
const text = value => value == null ? 'Not recorded' : typeof value === 'string' ? value : JSON.stringify(value, null, 2)
export default function RemediationCountDetails({ scanId, kind, expected, revision, onClose }) {
  const [result, setResult] = useState(null)
  const [retry, setRetry] = useState(0)
  const epoch = authEpoch()
  const review = kind === 'review'
  const unit = review ? 'review tasks' : 'verified change records'
  useEffect(() => {
    let active = true
    setResult(null)
    Promise.resolve().then(() => review ? listHitlQueue(scanId, 'pending') : getScanRemediationDiffs(scanId, true)).then(data => {
      if (!active || authEpoch() !== epoch) return
      const rows = review ? (Array.isArray(data) ? data : []) : remediationDiffPage(data).items
      setResult({ rows: rows.filter(row => !row.scan_id || row.scan_id === scanId) })
    }).catch(() => { if (active && authEpoch() === epoch) setResult({ error: true, rows: [] }) })
    return () => { active = false }
  }, [scanId, kind, revision, retry, epoch])
  const groups = new Map()
  for (const row of result?.rows || []) {
    const sc = scOf(row.rule_id || row.sc || row.wcag) || 'Not recorded'
    if (!groups.has(sc)) groups.set(sc, [])
    groups.get(sc).push(row)
  }
  return <Drawer title={review ? 'Pending review tasks' : 'Verified changes'} subtitle="Records behind this scan’s count" onClose={onClose}>
    <p>{expected} {unit} reported for this scan. {review ? 'Each task is one pending decision and may cover multiple findings.' : 'Each record is a stored before-and-after change from verification. This is not a count of original findings resolved.'}</p>
    {!result && <p role="status">Loading records…</p>}
    {result && <>
      <p role="status">{result.rows.length} of {expected} {unit} loaded across {groups.size} success criteria.</p>
      {(result.error || result.rows.length !== expected) && <p role="alert">{result.error ? 'Records could not be loaded.' : 'The records do not match the displayed count. The scan may have changed or the response may be incomplete.'} These details cannot yet explain the full total. <button type="button" onClick={() => setRetry(n => n + 1)}>Retry</button></p>}
      {[...groups].sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true })).map(([sc, rows]) => <details key={sc} className="remediation-fix-detail"><summary><strong>SC {sc}</strong> · {rows.length} {unit} · {new Set(rows.map(row => row.file || row.filename)).size} files</summary>
        {rows.map((row, index) => <article key={row.id || index} className="remediation-fix-detail">
          <h4>{row.file || row.filename || 'File not recorded'} · {review ? 'Review task' : 'Change'} {index + 1}</h4>
          {review ? <><p>{row.finding_count ?? 'Unknown number of'} findings · {row.status || 'pending'}</p><p className="remediation-evidence remediation-evidence--description">{row.reason || row.detail || row.description || 'No task description recorded.'}</p>
            {row.proposed_value != null && <div><p>Suggested fix</p><p className="remediation-evidence">{text(row.proposed_value)}</p></div>}</>
          : <dl><dt>Before</dt><dd className="remediation-evidence">{text(row.before)}</dd><dt>After</dt><dd className="remediation-evidence">{text(row.after)}</dd></dl>}
          {row.page != null && <p>Page {row.page}</p>}
          {(row.created_at || row.ts) && <p>Recorded: {row.created_at || row.ts}</p>}
          {row.id != null && <small>Record ID: {row.id}</small>}
        </article>)}
      </details>)}
    </>}
  </Drawer>
}

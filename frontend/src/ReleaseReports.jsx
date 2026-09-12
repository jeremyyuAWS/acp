import { useEffect, useRef, useState } from 'react'
import { getReleaseReports, retryReleaseReports, downloadReleaseReport } from './api.js'

export default function ReleaseReports({ scanId, publishedCount = 0, readOnly = false, read = getReleaseReports, retry = retryReleaseReports, download = downloadReleaseReport, files = [], results = {}, releaseId, children }) {
  const [state, setState] = useState(null)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [busy, setBusy] = useState(false)
  const currentScan = useRef(scanId)
  currentScan.current = scanId
  useEffect(() => {
    let live = true, timer, attempts = 0
    const controller = new AbortController()
    setState(null); setError(''); setBusy(false)
    if (!scanId) return () => controller.abort()
    const load = async () => {
      try {
        const result = await read(scanId, { signal: controller.signal })
        if (!live) return
        setState(result)
        attempts += 1
        if (['queued', 'publishing'].includes(result?.status) || (result?.status === 'not_started' && publishedCount > 0 && attempts < 12)) timer = setTimeout(load, 10000)
      } catch { if (live) setError('Reports could not be loaded.') }
    }
    load()
    return () => { live = false; clearTimeout(timer); controller.abort() }
  }, [scanId, publishedCount, refresh, read])
  const retryDelivery = async () => {
    setBusy(true); setError('')
    try { await retry(scanId); if (currentScan.current === scanId) setRefresh(n => n + 1) } catch { if (currentScan.current === scanId) setError('Report delivery could not be restarted.') } finally { if (currentScan.current === scanId) setBusy(false) }
  }
  const reportsByFile = {}
  const headerReports = []
  const sameRelease = state?.scan_id === scanId && !!releaseId && state?.release_id === releaseId
  for (const [index, report] of (state?.reports || []).entries()) {
    const result = results[report.file]
    const matches = sameRelease && ['changes', 'checklist'].includes(report.report_kind) && files.some(file => file.file === report.file)
      && result?.status === 'published' && !!report.artifact_digest && report.artifact_digest === result.artifact_digest
    if (matches && children) (reportsByFile[report.file] ||= []).push({ report, index })
    else headerReports.push({ report, index, unassigned: report.report_kind !== 'scan_summary' })
  }
  const reportLink = ({ report, index, unassigned }) => <li key={`${report.name}-${index}`}>
    {/^(https?):\/\//i.test(report.url || '') ? <a href={report.url} target="_blank" rel="noopener noreferrer">{report.name}</a> : <span>{report.name}</span>}
    {state?.bundle_id && report.download_url && <button type="button" className="linklike" style={{ marginLeft: 10 }} onClick={async () => { try { await download(scanId, state.bundle_id, index, report.name) } catch { if (currentScan.current === scanId) setError('The report could not be downloaded.') } }}>Download</button>}
    {children && unassigned && <small>Document version could not be matched to the current delivery receipt.</small>}
  </li>
  const reportSummary = <section aria-label="Release reports" style={{ marginTop: 16, borderTop: '1px solid var(--line)', paddingTop: 12 }}>
    <strong>Scan summary and per-file checklists</strong>
    {children && state?.release_id && state.release_id !== releaseId && <p className="muted">Reports describe release {state.release_id}; document actions below describe the current release.</p>}
    <p>Verified fixes, applied but unverified changes, remaining issues, and incomplete checks are recorded separately. Remaining work is a follow-up checklist; publication does not certify accessibility.</p>
    <p role="status">{!state ? (error ? '' : 'Checking reports…') : state.status === 'completed' ? (state.reports?.length && state.reports.every(report => /^https?:\/\//i.test(report.url || '')) ? 'Reports saved alongside the published files.' : 'Reports are ready to download.') : state.status === 'failed' ? 'Files may be published, but report delivery needs attention.' : ['queued', 'publishing'].includes(state.status) ? 'Preparing and saving reports alongside the published files…' : 'Reports are generated after files are published with reporting enabled.'}</p>
    {!!headerReports.length && <ul>{headerReports.map(reportLink)}</ul>}
    {state?.status === 'not_started' && <button type="button" className="linklike" onClick={() => setRefresh(n => n + 1)}>Refresh reports</button>}
    {state?.status === 'completed' && state.reports?.some(report => report.content_type !== 'application/pdf') && <button type="button" disabled={busy || readOnly} onClick={retryDelivery}>Generate PDF reports</button>}
    {state?.status === 'failed' && <button type="button" className="ghost small" disabled={busy || readOnly} onClick={retryDelivery}>Retry report delivery</button>}
    {error && <p role="alert">{error} <button type="button" className="linklike" onClick={() => setRefresh(n => n + 1)}>Refresh reports</button></p>}
  </section>
  if (typeof children === 'function') return children({ reportSummary, reportsByFile: Object.fromEntries(Object.entries(reportsByFile).map(([file, entries]) => [file, <ul key={file} className="release-file-reports" aria-label={`Reports for ${file}`}>{entries.map(reportLink)}</ul>])) })
  return reportSummary
}

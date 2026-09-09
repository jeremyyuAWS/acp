import { useEffect, useRef, useState } from 'react'
import { planReleaseContinuation, authorizeReleaseContinuation, getReleaseContinuation, resumeReleaseContinuation } from './api.js'
import './release-quick-actions.css'

export default function ReleaseQuickActions({ runId, files = [], ready = [], destination, folderName = '', destinationLabel,
  destinationPicker, readOnly, publishing, onReady, onProgress }) {
  const [plan, setPlan] = useState(null)
  const [active, setActive] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const lock = useRef(false)
  const progressRef = useRef(onProgress)
  progressRef.current = onProgress
  const key = JSON.stringify([runId, files.map(f => [f.file, f.corrected_sha256, f.remediated_at]), destination, folderName])
  const currentKey = useRef(key)
  currentKey.current = key
  useEffect(() => {
    let live = true
    setPlan(null); setError('')
    if (!runId || !files.length || readOnly) return
    const load = async () => {
      try {
        const result = await planReleaseContinuation(runId, files.map(f => f.file), destination, folderName)
        if (live) setPlan({ ...result, key })
      } catch (e) { if (live) setError(e?.message || 'Eligible changes could not be checked. Ready files can still be published.') }
    }
    load()
    return () => { live = false }
  }, [key, refresh, readOnly])
  useEffect(() => {
    let live = true, timer
    setActive(null)
    if (!runId || readOnly) return
    const poll = async () => {
      try {
        const result = await getReleaseContinuation(runId)
        if (!live) return
        if (result && (!result.id || !result.intent)) throw new Error('Release status is incomplete')
        setActive(result)
        if (result) progressRef.current?.(result)
      } catch { /* Keep the last durable state while reconnecting. */ }
      if (live) timer = setTimeout(poll, 4000)
    }
    poll()
    return () => { live = false; clearTimeout(timer) }
  }, [runId, refresh, readOnly])
  const entries = Object.entries(plan?.intent?.files || {})
  const eligible = entries.reduce((n, [, f]) => n + (f.rows || []).filter(r => r.authorize).reduce((sum, r) => sum + r.proposals.length, 0), 0)
  const eligibleFiles = entries.filter(([, f]) => (f.rows || []).some(r => r.authorize)).length
  const activeRunning = active && ['waiting', 'publishing'].includes(active.status)
  async function approve() {
    if (lock.current || readOnly || !eligible || !plan || plan.key !== currentKey.current || activeRunning) return
    lock.current = true; setBusy(true); setError('')
    const frozen = plan
    try {
      const result = await authorizeReleaseContinuation(runId, frozen.id)
      if (!result?.id || !result?.intent) throw new Error('Authorization status is incomplete. Refresh status before retrying.')
      if (currentKey.current === frozen.key) { setActive(result); setRefresh(n => n + 1) }
    } catch (e) {
      setError(e?.message || 'Authorization was not confirmed. Refresh status before retrying.')
      if (e?.status === 409) setPlan(null)
    } finally { lock.current = false; setBusy(false) }
  }
  async function retry() {
    if (lock.current || readOnly || !active) return
    lock.current = true; setBusy(true)
    try { setActive(await resumeReleaseContinuation(runId, active.id)); setRefresh(n => n + 1) }
    catch (e) { setError(e?.message || 'The same authorized delivery could not be resumed.') }
    finally { lock.current = false; setBusy(false) }
  }
  const outcomes = Object.entries(active?.progress || {}).filter(([file]) => file !== '_deadline')
  const count = state => outcomes.filter(([, result]) => result.state === state).length
  return <section className="panel release-quick" aria-label="Publish ready files and approved changes">
    <div className="release-quick-summary"><strong>{ready.length} ready to publish</strong><span>{files.length} files in this scope</span></div>
    <p><b>Destination:</b> {destinationLabel}. Originals stay unchanged.</p>
    {!readOnly && <details><summary>Change destination</summary>{destinationPicker}</details>}
    <div className="release-quick-buttons">
      <button className="qbtn approve" disabled={readOnly || publishing || !ready.length} onClick={() => onReady(ready.map(f => f.file))}>
        {publishing ? 'Publishing ready files…' : `Publish ready files (${ready.length})`}
      </button>
      {eligible > 0 && <button className="qbtn approve" disabled={readOnly || busy || activeRunning || plan.key !== key} onClick={approve}>
        {busy ? 'Authorizing…' : 'Approve eligible changes and publish when ready'}
      </button>}
    </div>
    {eligible > 0 && <p>{eligible} proposed {eligible === 1 ? 'change' : 'changes'} across {eligibleFiles} {eligibleFiles === 1 ? 'file' : 'files'}. This action authorizes the current proposals, applies them, verifies the result, and publishes qualifying files to the destination above. Individual inspection is optional.</p>}
    {!eligible && plan && !activeRunning && <p>{ready.length ? 'Other files do not hold eligible proposals for this action.' : 'No eligible proposals can be applied automatically yet.'} Manual work and verification blockers remain separate.</p>}
    {entries.length > 0 && <details><summary>Inspect proposed changes and remaining blockers</summary>
      {entries.map(([file, data]) => <div key={file}><b>{file}</b>
        {(data.rows || []).filter(r => r.authorize).map(r => <details key={r.id}><summary>{r.rule_id} · {r.proposals.length} proposed changes</summary>
          {r.proposals.map((p, i) => <p key={i}>{p.proposed_value}</p>)}</details>)}
        {(data.blockers || []).map(reason => <p key={reason}>{reason}</p>)}
      </div>)}
    </details>}
    {active && <div role="status" aria-label="Authorized Release progress">
      <b>{count('published')} delivered · {count('applying') + count('ready') + count('publishing')} in progress · {count('blocked') + count('failed') + count('needs_confirmation')} need attention</b>
      <p>{activeRunning ? 'Progress is saved. You can leave and return while approved changes are applied and verified.' : 'This authorized batch has finished. Files needing attention were not published.'}</p>
      <p>Authorized destination: {active.intent.destination?.folder_name || destinationLabel}</p>
      <details><summary>Delivery results and remaining work</summary>{outcomes.map(([file, result]) => <p key={file}><b>{file}</b>: {result.message}
        {result.receipt?.published_url && <> · <a href={result.receipt.published_url} target="_blank" rel="noopener noreferrer">Open delivered copy</a></>}</p>)}</details>
      {count('failed') > 0 && <button className="ghost" disabled={busy || readOnly || activeRunning} onClick={retry}>Retry failed delivery with the same authorization</button>}
    </div>}
    {error && <p role="alert">{error} <button className="linklike" onClick={() => setRefresh(n => n + 1)}>Refresh eligibility and status</button></p>}
  </section>
}

import { useEffect, useId, useRef, useState } from 'react'
import { getAutomaticRelease, enableAutomaticRelease, stopAutomaticRelease } from './api.js'
import LiveCounter from './LiveCounter.jsx'
import './remediation-auto-release.css'

const ACTIVE = new Set(['active', 'waiting', 'publishing', 'blocked'])
const defaultClient = { get: getAutomaticRelease, enable: enableAutomaticRelease, stop: stopAutomaticRelease }
export default function RemediationAutoRelease({ scanId, files = [], readOnly = false, client = defaultClient }) {
  const descriptionId = useId()
  const [state, setState] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [unconfirmed, setUnconfirmed] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const scope = [...new Set(files.map(f => typeof f === 'string' ? f : f.file).filter(Boolean))].sort()
  const key = JSON.stringify([scanId, scope])
  const currentKey = useRef(key)
  currentKey.current = key
  const lock = useRef(false)
  const mutationVersion = useRef(0)
  useEffect(() => {
    let live = true, timer
    const controller = new AbortController()
    setState(null); setLoading(true); setError(''); setUnconfirmed(false)
    if (!scanId) { setLoading(false); return }
    const load = async () => {
      const version = mutationVersion.current
      try {
        const result = await client.get(scanId, scope, { signal: controller.signal })
        if (!live || version !== mutationVersion.current) return
        setState(result); setError(''); setUnconfirmed(false)
      } catch (e) {
        if (live && version === mutationVersion.current) setError(e?.message || 'Automatic release status could not be loaded.')
      } finally {
        if (live) { setLoading(false); timer = setTimeout(load, 5000) }
      }
    }
    load()
    return () => { live = false; clearTimeout(timer); controller.abort() }
  }, [key, refresh, client])
  const authorization = state?.authorization
  const enabled = ACTIVE.has(authorization?.status)
  const destination = authorization?.destination_label || state?.destination_label
  const progress = authorization?.progress || {}
  const authorizedCount = authorization?.files?.length ?? 0
  const scopeChanged = enabled && JSON.stringify([...(authorization.files || [])].sort()) !== JSON.stringify(scope)
  async function change(checked) {
    if (lock.current || readOnly || !scanId) return
    if (checked && (!scope.length || !state?.available || !state?.run_id || !state?.destination)) return
    lock.current = true; mutationVersion.current += 1; setBusy(true); setError('')
    const frozenKey = key
    try {
      if (checked) {
        await client.enable(scanId, { run_id: state.run_id, files: scope,
          destination: state.destination, request_id: crypto.randomUUID(), allow_remaining_issues: true, include_reports: true })
      } else if (authorization?.id) {
        await client.stop(scanId, authorization.id)
      }
      if (currentKey.current === frozenKey) setRefresh(n => n + 1)
    } catch (e) {
      if (currentKey.current === frozenKey) { setUnconfirmed(true); setError(e?.message || 'The change was not confirmed. Refresh status before trying again.') }
    } finally { lock.current = false; setBusy(false) }
  }
  return <section className="rem-auto-release" aria-label="Automatic release">
    <label className="rem-auto-release-option">
      <input type="checkbox" checked={enabled} disabled={loading || busy || unconfirmed || readOnly || (!enabled && (!state?.available || !scope.length))}
        aria-describedby={descriptionId} onChange={e => change(e.target.checked)} />
      <strong>Fix and publish automatically</strong>
    </label>
    <div id={descriptionId}>
      <p>{authorization && !authorization.allow_remaining_issues ? 'This saved run releases files after its required approvals and verification pass.' : 'Saved copies publish after automatic processing, even when issues remain. Human inspection is optional; unapproved suggestions are not applied.'} Other files can keep processing.</p>
      {(!authorization || authorization.include_reports) && <p>A scan summary and per-file checklist accompany the files. Publishing does not certify accessibility.</p>}
      <p><b>Destination:</b> {destination || (loading ? 'Checking destination…' : 'Not available')}</p>
      {enabled ? <p>Enabled for {authorizedCount} file{authorizedCount === 1 ? '' : 's'} in this remediation run. You can leave this page; release continues in the background.</p>
        : authorization ? <p>{authorization.status === 'completed' ? 'Automatic release has finished for this run.' : 'Automatic release is off for this run.'}</p>
        : <p>This option is off until you select it. It authorizes release for this run only, for up to 24 hours.</p>}
      {enabled && authorization.expires_at && <p>Automatic release expires {new Date(authorization.expires_at).toLocaleString()}.</p>}
      {scopeChanged && <p>The authorization still covers the originally selected files. Changing the selection does not add files to automatic release.</p>}
      {!enabled && !loading && state?.reason && <p>{state.reason}</p>}
    </div>
    {authorization && <div className="rem-auto-release-progress">
      <dl aria-live="off">
        <div><dt>Released</dt><dd><LiveCounter value={progress.published || 0} /></dd></div>
        <div><dt>Waiting</dt><dd>{progress.pending || 0}</dd></div>
        <div><dt>Needs attention</dt><dd>{(progress.blocked || 0) + (progress.failed || 0)}</dd></div>
      </dl>
      {enabled && <button type="button" className="ghost" disabled={busy || unconfirmed || readOnly} onClick={() => change(false)}>Stop future releases</button>}
      <p>{authorization.status === 'stopped' ? 'Future releases stopped. Files already delivered remain available.' : enabled ? 'Stopping prevents future releases; a delivery already in progress may finish.' : authorization.status === 'completed' ? 'Automatic publication has finished. Any remaining accessibility work stays in the checklist.' : 'Files needing attention have not been released.'}</p>
    </div>}
    {busy && <p role="status">Saving automatic release…</p>}
    {error && <p role="alert">{error} <button type="button" className="linklike" disabled={busy} onClick={() => setRefresh(n => n + 1)}>Refresh status</button></p>}
  </section>
}

import { useEffect, useRef, useState } from 'react'
import { reconnectDriveForRelease } from './driveAuth.js'
import { authEpoch } from './apiIdentity.js'
import { refreshSPToken } from './spAuth.js'
import { setDriveToken, setSPToken } from './api.js'

export default function DriveReleaseReconnect({ scanId, authorizationId, onResume, readOnly = false, requiresReconnect = true, provider = 'drive' }) {
  const microsoft = provider === 'sharepoint'
  const providerName = microsoft ? 'SharePoint' : 'Google Drive'
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [resumed, setResumed] = useState(false)
  const lock = useRef(false)
  const identity = `${scanId}:${authorizationId}:${provider}`
  const current = useRef(identity)
  current.current = identity
  useEffect(() => () => { current.current = null }, [])
  useEffect(() => { setError(''); setResumed(false) }, [identity])
  async function reconnect() {
    if (lock.current || readOnly || !scanId || !authorizationId) return
    const frozen = identity
    const ownerEpoch = authEpoch()
    lock.current = true; setBusy(true); setError('')
    try {
      if (requiresReconnect) {
        const token = await (microsoft ? refreshSPToken({ persist: false }) : reconnectDriveForRelease())
        if (current.current !== frozen || authEpoch() !== ownerEpoch) return
        if (microsoft) setSPToken(token)
        else setDriveToken(token)
        try { sessionStorage.setItem(microsoft ? 'sp_token' : 'gd_token', token) } catch { /* Session storage may be unavailable. */ }
      }
      if (authEpoch() !== ownerEpoch) return
      await onResume()
      if (current.current === frozen && authEpoch() === ownerEpoch) setResumed(true)
    } catch (e) {
      if (current.current === frozen && authEpoch() === ownerEpoch) setError(e?.message || 'The saved release could not resume. Refresh status before trying again.')
    } finally { lock.current = false; setBusy(false) }
  }
  return <div className="rem-auto-release-attention">
    <p>{requiresReconnect ? `${providerName} access needs to be renewed. Sign in with the account that owns this release.` : 'Resume delivery after ACP checks whether a saved copy already exists.'} Saved files, destination, and approval choices stay the same.</p>
    <button type="button" className="ghost" disabled={readOnly || busy || resumed} onClick={reconnect}>{busy ? (requiresReconnect ? `Reconnecting ${providerName}…` : 'Resuming delivery…') : requiresReconnect ? `Reconnect ${providerName} and resume` : 'Resume delivery'}</button>
    {resumed && <p role="status">ACP is checking delivery and resuming the saved release.</p>}
    {error && <p role="alert">{error}</p>}
  </div>
}

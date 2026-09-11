import { useEffect, useRef, useState } from 'react'
import { reconnectDriveForRelease } from './driveAuth.js'
import { authEpoch } from './apiIdentity.js'
import { setDriveToken } from './api.js'

export default function DriveReleaseReconnect({ scanId, authorizationId, onResume, readOnly = false, requiresReconnect = true }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [resumed, setResumed] = useState(false)
  const lock = useRef(false)
  const identity = `${scanId}:${authorizationId}`
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
        const token = await reconnectDriveForRelease()
        if (current.current !== frozen || authEpoch() !== ownerEpoch) return
        setDriveToken(token)
        try { sessionStorage.setItem('gd_token', token) } catch { /* Session storage may be unavailable. */ }
      }
      if (authEpoch() !== ownerEpoch) return
      await onResume()
      if (current.current === frozen && authEpoch() === ownerEpoch) setResumed(true)
    } catch (e) {
      if (current.current === frozen && authEpoch() === ownerEpoch) setError(e?.message || 'The saved release could not resume. Refresh status before trying again.')
    } finally { lock.current = false; setBusy(false) }
  }
  return <div className="rem-auto-release-attention">
    <p>{requiresReconnect ? 'Google Drive access needs to be renewed. Sign in with the account that owns this release.' : 'Resume delivery after ACP checks whether a saved copy already exists.'} Saved files, destination, and approval choices stay the same.</p>
    <button type="button" className="ghost" disabled={readOnly || busy || resumed} onClick={reconnect}>{busy ? (requiresReconnect ? 'Reconnecting Google Drive…' : 'Resuming delivery…') : requiresReconnect ? 'Reconnect Google Drive and resume' : 'Resume delivery'}</button>
    {resumed && <p role="status">ACP is checking delivery and resuming the saved release.</p>}
    {error && <p role="alert">{error}</p>}
  </div>
}

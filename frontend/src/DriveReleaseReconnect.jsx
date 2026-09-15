import { useEffect, useRef, useState } from 'react'
import { authEpoch } from './apiIdentity.js'
import { reconnectDriveForRelease } from './driveAuth.js'
import { refreshSPToken } from './spAuth.js'
import { setDriveToken, setSPToken } from './api.js'
import useAutomaticDeliveryRecovery, { recoveryKey } from './useAutomaticDeliveryRecovery.js'
import ReleaseRecoveryBanner from './ReleaseRecoveryBanner.jsx'

export default function DriveReleaseReconnect({ scanId, authorizationId, authorization, owner,
  onResume, onRefresh, readOnly = false, requiresReconnect = true, provider = 'drive' }) {
  const microsoft = provider === 'sharepoint'
  const key = recoveryKey({ scanId, authorization, owner, provider })
  const enabled = !readOnly && authorization?.id === authorizationId && Boolean(key)
    && (authorization.can_resume === true || authorization.requires_reconnect === true)
  const recovery = useAutomaticDeliveryRecovery({ key, enabled, requiresReconnect, microsoft,
    renew: interactive => microsoft ? refreshSPToken({ interactive, persist: false }) : reconnectDriveForRelease(),
    install: token => {
      if (microsoft) setSPToken(token)
      else setDriveToken(token)
      try { sessionStorage.setItem(microsoft ? 'sp_token' : 'gd_token', token) } catch { /* Session storage unavailable. */ }
    }, resume: onResume, refresh: onRefresh,
  })
  if (!authorization && scanId && authorizationId && typeof onResume === 'function' && requiresReconnect)
    return <ManualReleaseReconnect {...{ scanId, authorizationId, onResume, readOnly, microsoft }} />
  // Retired the unconfirmed top-of-page notice; keep recovery running and the
  // banner implementation available for explicit sign-in and active recovery.
  if (recovery.status === 'unconfirmed') return null
  return <ReleaseRecoveryBanner status={enabled ? recovery.status : 'idle'}
    providerName={microsoft ? 'SharePoint' : 'Google Drive'} error={recovery.error}
    onReconnect={recovery.reconnect} onCheckStatus={recovery.checkStatus} disabled={readOnly} />
}

// Compatibility for the existing explicit manual continuation. Only its button can
// request access and resume; the server revalidates the saved owner's authority.
// Missing full automatic authorization must never start an automatic operation.
function ManualReleaseReconnect({ scanId, authorizationId, onResume, readOnly, microsoft }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [resumed, setResumed] = useState(false)
  const lock = useRef(false)
  const identity = `${scanId}:${authorizationId}:${microsoft}`
  const current = useRef(identity)
  current.current = readOnly ? null : identity
  useEffect(() => {
    current.current = readOnly ? null : identity
    return () => { current.current = null }
  }, [])
  async function reconnect() {
    if (lock.current || readOnly) return
    const frozen = identity, epoch = authEpoch()
    lock.current = true; setBusy(true); setError('')
    try {
      const token = await (microsoft ? refreshSPToken({ interactive: true, persist: false }) : reconnectDriveForRelease())
      if (current.current !== frozen || authEpoch() !== epoch) return
      if (microsoft) setSPToken(token)
      else setDriveToken(token)
      try { sessionStorage.setItem(microsoft ? 'sp_token' : 'gd_token', token) } catch { /* Session storage unavailable. */ }
      await onResume()
      if (current.current === frozen && authEpoch() === epoch) setResumed(true)
    } catch (e) {
      if (current.current === frozen && authEpoch() === epoch) setError(e?.message || 'Delivery could not resume.')
    } finally { lock.current = false; if (current.current === frozen) setBusy(false) }
  }
  const providerName = microsoft ? 'SharePoint' : 'Google Drive'
  return <div className="rem-auto-release-attention">
    <p>{providerName} access needs to be renewed for the saved manual release.</p>
    <button type="button" className="ghost" disabled={readOnly || busy || resumed} onClick={reconnect}>
      {busy ? `Reconnecting ${providerName}…` : `Reconnect ${providerName} and resume`}
    </button>
    {resumed && <p role="status">ACP is checking delivery and resuming the saved release.</p>}
    {error && <p role="alert">{error}</p>}
  </div>
}

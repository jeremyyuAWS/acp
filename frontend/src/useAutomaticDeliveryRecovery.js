import { useCallback, useEffect, useRef, useState } from 'react'
import { apiBase, authEpoch } from './apiIdentity.js'

const attempts = new Map()
const PREFIX = 'acp.delivery-recovery.v1:'
export function recoveryKey({ scanId, authorization, owner, provider }) {
  if (!owner || !scanId || !authorization?.id || !authorization.run_id
      || !Number.isInteger(authorization.revision)
      || !['active', 'waiting', 'processing', 'publishing', 'blocked'].includes(authorization.status)
      || authorization.resumable === false
      || (authorization.expires_at && !(Date.parse(authorization.expires_at) > Date.now()))) return null
  return PREFIX + JSON.stringify([apiBase(), owner, scanId, authorization.id,
    authorization.run_id, authorization.revision, provider, authorization.source_revision,
    authorization.destination, [...(authorization.files || [])].sort()])
}
function remembered(key) {
  if (attempts.has(key)) return attempts.get(key)
  try { return JSON.parse(sessionStorage.getItem(key) || 'null') } catch { return null }
}
function remember(key, status) {
  attempts.set(key, status)
  try { sessionStorage.setItem(key, JSON.stringify(status)) } catch { /* In-memory lock remains. */ }
}
export function _resetRecoveryAttempts() { attempts.clear() }

export default function useAutomaticDeliveryRecovery({ key, enabled, requiresReconnect,
  microsoft, renew, resume, refresh, install, timeoutMs = 20000 }) {
  const [state, setState] = useState({ status: 'idle', error: '' })
  const latest = useRef({ key, enabled, renew, resume, refresh, install })
  latest.current = { key, enabled, renew, resume, refresh, install }
  const operation = useRef(null)
  const run = useCallback(async (interactive = false) => {
    const snapshot = latest.current
    if (!snapshot.key || !snapshot.enabled || operation.current) return
    if (!interactive && remembered(snapshot.key)) {
      setState({ status: remembered(snapshot.key)?.status === 'sign_in' ? 'sign_in' : 'checking', error: '' })
      // Durable GET polling in the parent reconciles accepted/uncertain requests.
      return
    }
    const epoch = authEpoch()
    const job = { live: true, cancel: null, timer: null }
    operation.current = job
    const current = () => job.live && latest.current.key === snapshot.key
      && latest.current.enabled && authEpoch() === epoch
    setState({ status: 'recovering', error: '' })
    remember(snapshot.key, { status: 'pending' })
    try {
      await Promise.race([
        (async () => {
          if (requiresReconnect) {
            const token = await snapshot.renew(interactive)
            if (!current()) return
            if (!token) throw new Error('Provider sign-in is required.')
            snapshot.install(token)
          }
          if (!current()) return
          job.resumeStarted = true
          await snapshot.resume()
          if (current()) {
            remember(snapshot.key, { status: 'accepted' })
            setState({ status: 'checking', error: '' })
            snapshot.refresh?.()
          }
        })(),
        new Promise((_, reject) => {
          job.cancel = () => reject(new Error('Cancelled'))
          job.timer = setTimeout(() => {
            job.live = false
            reject(new Error('Delivery recovery was not confirmed. ACP will check the saved status before another attempt.'))
          }, timeoutMs)
        }),
      ])
    } catch (error) {
      if (latest.current.key === snapshot.key && authEpoch() === epoch && operation.current === job) {
        const interaction = requiresReconnect && !job.resumeStarted && job.live
          && (interactive || !microsoft || /interaction_required|login_required|consent_required|no active Microsoft account/i.test(error?.errorCode || error?.message || ''))
        remember(snapshot.key, { status: interaction ? 'sign_in' : 'uncertain' })
        setState({ status: interaction ? 'sign_in' : 'checking',
          error: interaction && !interactive ? '' : error?.message || 'Delivery recovery is unconfirmed.' })
        if (job.resumeStarted) snapshot.refresh?.()
      }
    } finally {
      job.live = false; clearTimeout(job.timer)
      if (operation.current === job) operation.current = null
    }
  }, [requiresReconnect, microsoft, timeoutMs])
  useEffect(() => {
    setState({ status: 'idle', error: '' })
    let mounted = true
    if (key && enabled) {
      if (requiresReconnect && !microsoft) setState({ status: 'sign_in', error: '' })
      else queueMicrotask(() => { if (mounted) run(false) })
    }
    return () => {
      mounted = false
      const job = operation.current
      if (job) { job.live = false; clearTimeout(job.timer); job.cancel?.(); operation.current = null }
    }
  }, [key, enabled, requiresReconnect, microsoft, run])
  return { ...state, reconnect: () => run(true) }
}

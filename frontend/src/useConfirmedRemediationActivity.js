import { useEffect, useState } from 'react'

const FRESH_MS = 60_000
const activeAttempts = snapshot => Array.isArray(snapshot?.active_attempts) ? snapshot.active_attempts : []

// Queue size and review decisions are not evidence of a currently working process.
export function confirmedRemediationActivity(snapshot, now = Date.now()) {
  if (!snapshot || snapshot.terminal || !Number.isFinite(now)) return false
  if (snapshot.state !== 'running' && !(snapshot.state === 'needs_attention' && Array.isArray(snapshot.also) && snapshot.also.includes('running'))) return false
  const generated = Date.parse(snapshot.generated_at || '')
  if (!Number.isFinite(generated) || now - generated < -5_000 || now - generated >= FRESH_MS) return false
  if (Array.isArray(snapshot.integrity?.affected) && snapshot.integrity.affected.some(key => key === 'documents' || key === 'freshness')) return false
  const processing = snapshot.documents?.processing
  return (Number.isSafeInteger(processing) && processing > 0 && snapshot.progress?.lease_healthy === true)
    || activeAttempts(snapshot).some(attempt => attempt?.lease_valid === true && Date.parse(attempt.lease_expires_at || '') > now)
}

export default function useConfirmedRemediationActivity(snapshot) {
  const [hidden, setHidden] = useState(() => typeof document !== 'undefined' && document.hidden)
  const [, tick] = useState(0)
  const now = Date.now()
  const active = !hidden && confirmedRemediationActivity(snapshot, now)
  useEffect(() => {
    const update = () => { setHidden(document.hidden); tick(value => value + 1) }
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])
  useEffect(() => {
    if (!active) return undefined
    // Stop exactly at the next expiry, with at most five seconds between checks.
    const freshUntil = Date.parse(snapshot.generated_at) + FRESH_MS
    const processing = snapshot.documents?.processing
    const processingActive = Number.isSafeInteger(processing) && processing > 0 && snapshot.progress?.lease_healthy === true
    const leaseUntil = processingActive ? Infinity : Math.max(...activeAttempts(snapshot).filter(attempt => attempt?.lease_valid === true).map(attempt => Date.parse(attempt.lease_expires_at || '')).filter(Number.isFinite))
    const delay = Math.max(1, Math.min(5_000, freshUntil - now, leaseUntil - now))
    const timer = setTimeout(() => tick(value => value + 1), delay)
    return () => clearTimeout(timer)
  }, [active, snapshot, now])
  return active
}

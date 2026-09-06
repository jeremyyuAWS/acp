import { useState, useEffect, useRef } from 'react'
import { getScanLive } from './api'
import { isNewerFrame } from './liveAssessment.js'

// Polls GET /scans/{sid}/live while a scan is active, for the running-screen panel. Kept as a hook (not
// inline in App.jsx) so the wiring is testable and the mount stays one line.
//
// Three correctness rules the running screen depends on:
//  * sequence-guarded — a slow or out-of-order response can never overwrite newer state (reconnect-safe),
//  * fail-soft — a transient poll error is swallowed and the LAST GOOD snapshot is retained, so a blip
//    never blanks the panel mid-scan. Stops cleanly when scanId is falsy or `active` goes false.
//  * refocus-fresh — when a backgrounded tab becomes visible again it polls immediately, so the operator
//    who tabs back sees current state instantly instead of waiting up to one interval for stale data.
export function useLiveSnapshot(scanId, { active = true, intervalMs = 2000 } = {}) {
  const [snapshot, setSnapshot] = useState(null)
  const seqRef = useRef(null)
  const scanRef = useRef(null)

  useEffect(() => {
    // An inactive stage must not keep rendering the last frame it fetched. App turns this hook
    // off when Remediate owns the screen; retaining the completed assessment snapshot here made
    // that old card remain above the live remediation card even though the stage gate was false.
    if (!scanId || !active) {
      scanRef.current = null
      seqRef.current = null
      setSnapshot(null)
      return undefined
    }
    // Likewise, never show one scan's frame while the first poll for another scan is pending.
    if (scanRef.current !== scanId) {
      scanRef.current = scanId
      seqRef.current = null
      setSnapshot(null)
    }
    let cancelled = false
    let timer = null
    let unchanged = 0
    let failures = 0
    let lastContent = null

    // Assess is an authenticated snapshot feed rather than EventSource. Keep it close to live
    // while work is moving, but do not make every open browser re-run the same database reads at
    // full speed while a queue is idle. Discover and Remediate retain their push streams; this is
    // their proxy-safe counterpart for Assess.
    const MAX_IDLE_MS = Math.max(intervalMs, 8000)
    const contentKey = (s) => {
      if (!s || typeof s !== 'object') return String(s)
      const { generated_at: _generatedAt, _live: _transport, ...content } = s
      try { return JSON.stringify(content) } catch { return String(s.sequence ?? '') }
    }

    const schedule = (delay) => {
      clearTimeout(timer)
      if (cancelled) return
      // A hidden tab gets one immediate refresh when it returns; it does not need to keep a
      // server and database busy while nobody can see the animation.
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
      timer = setTimeout(poll, delay)
    }

    const poll = async () => {
      try {
        const s = await getScanLive(scanId)
        if (cancelled || !s) return
        failures = 0
        const key = contentKey(s)
        unchanged = key === lastContent ? unchanged + 1 : 0
        lastContent = key
        if (isNewerFrame(seqRef.current, s.sequence)) {
          if (typeof s.sequence === 'number') seqRef.current = s.sequence
          setSnapshot({ ...s, _live: { mode: 'live', measuredAt: Date.now() } })
        } else {
          // Queue activity can change without the completed-document sequence increasing. Keep
          // the newest authoritative frame; the sequence guard only rejects genuinely older data.
          const current = seqRef.current
          if (typeof s.sequence !== 'number' || current == null || s.sequence === current) {
            setSnapshot({ ...s, _live: { mode: 'live', measuredAt: Date.now() } })
          }
        }
      } catch {
        failures += 1
        // Preserve the last good values and make the interruption visible. The next successful
        // response replaces this marker without making the card disappear.
        setSnapshot((previous) => previous
          ? { ...previous, _live: { ...(previous._live || {}), mode: 'reconnecting' } }
          : previous)
      } finally {
        if (!cancelled) {
          const idleDelay = Math.min(MAX_IDLE_MS, intervalMs * (2 ** Math.min(unchanged, 2)))
          const retryDelay = Math.min(MAX_IDLE_MS, intervalMs * (2 ** Math.min(failures, 2)))
          schedule(failures ? retryDelay : idleDelay)
        }
      }
    }

    poll()
    // Snap to current the moment a backgrounded tab is shown again (don't wait out the interval).
    const onVisible = () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'visible') {
        clearTimeout(timer)
        poll()
      }
    }
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      clearTimeout(timer)
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisible)
    }
  }, [scanId, active, intervalMs])

  return snapshot
}

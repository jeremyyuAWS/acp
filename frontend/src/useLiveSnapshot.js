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

  useEffect(() => {
    if (!scanId || !active) return undefined
    let cancelled = false

    const poll = async () => {
      try {
        const s = await getScanLive(scanId)
        if (cancelled || !s) return
        if (isNewerFrame(seqRef.current, s.sequence)) {
          if (typeof s.sequence === 'number') seqRef.current = s.sequence
          setSnapshot(s)
        }
      } catch {
        /* transient — keep the last good snapshot rather than blanking the panel */
      }
    }

    poll()
    const iv = setInterval(poll, intervalMs)
    // Snap to current the moment a backgrounded tab is shown again (don't wait out the interval).
    const onVisible = () => { if (typeof document !== 'undefined' && document.visibilityState === 'visible') poll() }
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      clearInterval(iv)
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisible)
    }
  }, [scanId, active, intervalMs])

  return snapshot
}

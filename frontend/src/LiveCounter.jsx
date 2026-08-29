import { useEffect, useRef, useState } from 'react'
import { shouldAnimate, deltaFor, interpolate } from './liveCounterAnim.js'

const COUNT_UP_MS = 400
const DELTA_VISIBLE_MS = 2000

function prefersReducedMotion() {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
    : false
}

// A number that counts up (not just jumps) when it increases, with a brief "+N" beside it — the
// only visual confirmation, on a source with many folders, that discovery is still doing real
// work while the checklist keeps showing the same step for minutes at a time.
//
// Deliberately reactive only to its OWN `value` prop — batching how OFTEN a new value arrives is
// the caller's job (App.jsx's existing 1s poll tick, scanner.py's 2s progress_cb throttle); this
// only decides how to PRESENT a value that already changed, once, not how often to ask for one.
//
// Never animates or highlights on mount, or on a DECREASE (a recount/truncation correction) — see
// liveCounterAnim.js's docstring for why a decrease must never read as green progress.
//
// The count-up itself is skipped under prefers-reduced-motion (checked directly, since
// requestAnimationFrame is not a CSS transition/animation and the app's global reduced-motion
// rule in styles.css can't reach it); the "+N" flash IS a CSS animation, so that rule already
// neutralizes it without any extra code here.
export default function LiveCounter({ value }) {
  const prevRef = useRef(null)
  const [display, setDisplay] = useState(value ?? 0)
  const [delta, setDelta] = useState(null)
  const rafRef = useRef(null)
  const deltaTimerRef = useRef(null)

  useEffect(() => {
    const prev = prevRef.current
    prevRef.current = value
    if (value == null) return undefined

    const d = deltaFor(prev, value)
    if (d != null) {
      setDelta(d)
      clearTimeout(deltaTimerRef.current)
      deltaTimerRef.current = setTimeout(() => setDelta(null), DELTA_VISIBLE_MS)
    }

    if (!shouldAnimate(prev, value) || prefersReducedMotion()) {
      setDisplay(value)
      return undefined
    }

    cancelAnimationFrame(rafRef.current)
    const from = prev
    const to = value
    // `start` is captured from the FIRST rAF callback's own timestamp, not a separately-read
    // performance.now() beforehand — the two are the same clock per spec, but relying on that
    // rather than using rAF's own timestamp end to end is an unforced assumption this component
    // doesn't need to make.
    let start = null
    const tick = (now) => {
      if (start == null) start = now
      const elapsed = now - start
      setDisplay(interpolate(from, to, elapsed, COUNT_UP_MS))
      if (elapsed < COUNT_UP_MS) rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [value])

  // Unmount cleanup only — the effect above already cleans up between value changes.
  useEffect(() => () => {
    clearTimeout(deltaTimerRef.current)
    cancelAnimationFrame(rafRef.current)
  }, [])

  return (
    <span className="livecounter">
      <span className={delta != null ? 'livecounter-n flash' : 'livecounter-n'}>
        {(display ?? 0).toLocaleString()}
      </span>
      {delta != null && (
        <span className="livecounter-delta" aria-hidden="true">+{delta.toLocaleString()}</span>
      )}
    </span>
  )
}

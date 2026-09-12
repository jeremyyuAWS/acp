import { useEffect, useRef, useState } from 'react'

// Signed updates deliberately differ from the discovery counter: draining queues
// are meaningful progress too, and are shown in the tile's own status color.
export default function BidirectionalKpiCounter({ value, animate = true }) {
  const previous = useRef(value)
  const [display, setDisplay] = useState(value)
  const displayed = useRef(value)
  const [delta, setDelta] = useState(null)
  useEffect(() => {
    const from = previous.current
    previous.current = value
    if (!animate || !Number.isFinite(from) || !Number.isFinite(value) || from === value) {
      setDelta(null)
      displayed.current = value
      setDisplay(value)
      return undefined
    }
    setDelta(value - from)
    const timeout = setTimeout(() => setDelta(null), 2000)
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduced) { displayed.current = value; setDisplay(value); return () => clearTimeout(timeout) }
    const animationFrom = Number.isFinite(displayed.current) ? displayed.current : from
    let frame, start
    const tick = now => {
      start ??= now
      const portion = Math.min(1, (now - start) / 400)
      displayed.current = Math.round(animationFrom + (value - animationFrom) * portion)
      setDisplay(displayed.current)
      if (portion < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => { clearTimeout(timeout); cancelAnimationFrame(frame) }
  }, [value, animate])
  return <span className="kpi-counter"><span>{Number.isFinite(display) ? display.toLocaleString() : '—'}</span>
    {delta != null && <span className="kpi-update-delta livecounter-delta" aria-hidden="true">{delta > 0 ? '+' : '−'}{Math.abs(delta).toLocaleString()}</span>}</span>
}

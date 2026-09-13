import { useEffect, useRef, useState } from 'react'
import './kpi-counter-activity.css'

// Changes are activity; only movement in the caller's successful direction is
// improvement. Queue reductions and completed-work increases share green deltas.
export default function BidirectionalKpiCounter({ value, animate = true, positiveDirection = 'neutral' }) {
  const previous = useRef(value)
  const displayed = useRef(value)
  const sequence = useRef(0)
  const [display, setDisplay] = useState(value)
  const [activity, setActivity] = useState(null)
  useEffect(() => {
    const from = previous.current
    previous.current = value
    if (!animate || !Number.isFinite(from) || !Number.isFinite(value) || from === value) {
      setActivity(null)
      displayed.current = value
      setDisplay(value)
      return undefined
    }
    setActivity({ delta: value - from, sequence: ++sequence.current })
    const timeout = setTimeout(() => setActivity(null), 2000)
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
  const delta = activity?.delta
  const improving = positiveDirection === 'increase' ? delta > 0 : positiveDirection === 'decrease' && delta < 0
  const tone = positiveDirection === 'neutral' ? 'neutral' : improving ? 'positive' : 'warning'
  return <span className="kpi-counter"><span key={`value-${activity?.sequence ?? 0}`} className={activity ? 'kpi-counter-value kpi-counter-value--activity' : 'kpi-counter-value'}>{Number.isFinite(display) ? display.toLocaleString() : '—'}</span>
    {activity && <span key={activity.sequence} className={`kpi-update-delta livecounter-delta kpi-update-delta--${tone} kpi-update-delta--${delta > 0 ? 'increase' : 'decrease'}`} aria-hidden="true">{delta > 0 ? '+' : '−'}{Math.abs(delta).toLocaleString()}</span>}</span>
}

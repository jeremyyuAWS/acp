import { useEffect, useRef, useState } from 'react'

// Compare settled forecasts only. Loading gaps retain the last valid baseline;
// changing assessments or scope starts a new baseline without a misleading delta.
export function useForecastDelta(value, context, setting) {
  const previous = useRef(null)
  const timer = useRef(null)
  const serial = useRef(0)
  const [delta, setDelta] = useState(null)
  useEffect(() => {
    const before = previous.current
    if (before && before.context !== context) {
      clearTimeout(timer.current)
      setDelta(null)
      previous.current = null
    }
    if (!Number.isFinite(value) || setting == null) return
    const baseline = previous.current
    previous.current = { value, context, setting }
    if (!baseline || baseline.setting === setting) return
    clearTimeout(timer.current)
    const amount = value - baseline.value
    setDelta(amount ? { amount, id: ++serial.current } : null)
    if (amount) timer.current = setTimeout(() => setDelta(null), 2000)
  }, [value, context, setting])
  useEffect(() => () => clearTimeout(timer.current), [])
  return delta
}

import { useRef, useState, useEffect } from 'react'
import { recordSample, estimate, etaRangeText } from './throughputEta.js'

// Accumulates progress samples across successive snapshots and returns the rolling rate + calibrated ETA
// range, ready for display: { ratePerMin, etaText, calibrating }. Samples are stamped on the wall clock.
//
// Resets when the run id changes — a new scan must start its own calibration, never inherit the previous
// run's samples (which would show a confident-but-wrong ETA for the first seconds of the new run).
export function useThroughput(runId, done, remaining) {
  const histRef = useRef([])
  const idRef = useRef(runId)
  const [out, setOut] = useState({ ratePerMin: null, etaText: null, calibrating: true })

  useEffect(() => {
    if (idRef.current !== runId) { histRef.current = []; idRef.current = runId }   // new run → fresh
    if (typeof done !== 'number') return
    histRef.current = recordSample(histRef.current, done, Date.now())
    const e = estimate(histRef.current, remaining)
    setOut({ ratePerMin: e.ratePerMin, etaText: etaRangeText(e.eta), calibrating: e.calibrating })
  }, [runId, done, remaining])

  return out
}

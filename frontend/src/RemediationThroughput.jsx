import { useEffect, useState } from 'react'
import LiveThroughput from './LiveThroughput.jsx'

// The API supplies counts per 30-second bucket, not cumulative totals. Start at
// zero and accumulate only measured buckets so the shared stage chart remains honest.
export function remediationThroughputPoints(buckets) {
  if (!Array.isArray(buckets) || !buckets.length) return []
  const samples = buckets.slice(-10)
  if (samples.some(value => !Number.isSafeInteger(value) || value < 0)) return []
  return samples.reduce((points, value) => [...points, points.at(-1) + value], [0])
}

export default function RemediationThroughput({ data, identity, paused = false, mini = false }) {
  const [shown, setShown] = useState({ identity, data })
  useEffect(() => {
    setShown(previous => previous.identity !== identity || !paused ? { identity, data } : previous)
  }, [data, identity, paused])
  const current = (shown.identity === identity ? shown.data : data) || {}
  const points = remediationThroughputPoints(current.buckets)
  const rate = current.documents_per_minute
  if (!Number.isFinite(rate) || rate < 0) return null
  if (points.length < 2) return mini ? null : <p><strong>{rate.toLocaleString()} documents/min</strong></p>
  const chart = <LiveThroughput mini={mini} compact={!mini} points={points} ratePerMin={rate}
    label="Document processing · last 5 minutes" unitLabel="processed"
    sampleLabel="time points" />
  return mini ? <div className="wf-throughput-mini"><span>{rate.toLocaleString()} documents/min</span>{chart}</div> : chart
}

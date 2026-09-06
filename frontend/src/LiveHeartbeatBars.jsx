import { useEffect, useMemo, useState } from 'react'
import './live-heartbeat-bars.css'

export function heartbeatBuckets(updates = [], now = Date.now(), slots = 12, bucketMs = 5000) {
  const values = Array.from({ length: slots }, () => 0)
  const start = now - slots * bucketMs
  updates.forEach((stamp) => {
    const at = Number(stamp)
    if (!Number.isFinite(at) || at <= start || at > now) return
    const index = Math.min(slots - 1, Math.floor((at - start) / bucketMs))
    values[index] += 1
  })
  return values
}

// A rolling record of successful snapshot heartbeats, not document throughput. Assess can stay
// live while a large file produces no completed-document delta; this strip still proves that the
// authenticated feed is answering. Twelve five-second buckets shift left as time advances.
export default function LiveHeartbeatBars({ measuredAt, slots = 12 }) {
  const [updates, setUpdates] = useState(() => {
    const stamp = Number(measuredAt)
    return Number.isFinite(stamp) && stamp > 0 ? [stamp] : []
  })
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const stamp = Number(measuredAt)
    if (!Number.isFinite(stamp) || stamp <= 0) return
    setUpdates((current) => current.at(-1) === stamp
      ? current
      : [...current, stamp].filter((at) => stamp - at < slots * 5000).slice(-slots * 3))
    setNow(Date.now())
  }, [measuredAt, slots])

  useEffect(() => {
    if (!updates.length) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [updates.length])

  const buckets = useMemo(() => heartbeatBuckets(updates, now, slots), [updates, now, slots])
  const total = buckets.reduce((sum, value) => sum + value, 0)
  if (!total) return null
  const max = Math.max(1, ...buckets)

  return (
    <span className="live-heartbeat-bars"
          role="img" aria-label={`Last 60 seconds: ${total} successful live update${total === 1 ? '' : 's'}`}>
      {buckets.map((value, index) => (
        <i key={index} aria-hidden="true"
           style={{ height: `${Math.max(2, value / max * 16)}px`, opacity: value ? 1 : 0.2 }} />
      ))}
    </span>
  )
}

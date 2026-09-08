import { useEffect, useRef, useState } from 'react'
import './live-heartbeat-bars.css'

// Canonical lineage is refreshed every 15 seconds (useCanonicalStageLineage). Match that real
// sampling cadence instead of implying that ACP observed three times as many five-second windows.
export const HEARTBEAT_SLOTS = 4
export const HEARTBEAT_INTERVAL_MS = 15_000
const histories = new Map()

export function heartbeatBuckets(updates = [], now = Date.now(), slots = HEARTBEAT_SLOTS,
  bucketMs = HEARTBEAT_INTERVAL_MS) {
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

export function retainedHeartbeatHistory(updates = [], now = Date.now(), slots = HEARTBEAT_SLOTS,
  bucketMs = HEARTBEAT_INTERVAL_MS) {
  return heartbeatBuckets(updates, now, slots, bucketMs)
}

function timestamp(value) {
  const numeric = Number(value)
  if (Number.isFinite(numeric) && numeric > 0) return numeric
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : null
}

// A rolling record of successful snapshot heartbeats, not document throughput. Assess can stay
// live while a large file produces no completed-document delta; this strip still proves that the
// authenticated feed is answering. Four fifteen-second buckets cover the last minute, matching
// the canonical lineage poll that supplies measuredAt.
function historyFor(key, measuredAt) {
  const stamp = timestamp(measuredAt)
  const current = histories.get(key) || []
  if (!stamp || current.at(-1) === stamp) return current
  const next = [...current, stamp].filter((at) => stamp - at < HEARTBEAT_SLOTS * HEARTBEAT_INTERVAL_MS)
  histories.set(key, next)
  return next
}

export function refreshedAge(measuredAt, now = Date.now()) {
  const stamp = timestamp(measuredAt)
  if (!stamp) return 'awaiting refresh'
  const seconds = Math.max(0, Math.floor((now - stamp) / 1000))
  if (seconds < 5) return 'refreshed now'
  if (seconds < 60) return `refreshed ${seconds}s ago`
  return `refreshed ${Math.floor(seconds / 60)}m ago`
}

export default function LiveHeartbeatBars({ measuredAt, stage = 'assess', historyKey = stage,
  terminal = false, showText = false }) {
  const key = String(historyKey || stage)
  const [updates, setUpdates] = useState(() => historyFor(key, measuredAt))
  const [now, setNow] = useState(() => Date.now())
  const [lastSignal, setLastSignal] = useState(() => timestamp(measuredAt))
  const frozen = useRef(terminal)
  const previousKey = useRef(key)

  useEffect(() => {
    if (previousKey.current === key) return
    previousKey.current = key
    frozen.current = terminal
    const next = historyFor(key, measuredAt)
    setUpdates(next)
    setLastSignal(timestamp(measuredAt))
    setNow(Date.now())
  }, [key, measuredAt, terminal])

  useEffect(() => {
    const stamp = timestamp(measuredAt)
    if (!stamp || frozen.current) return
    setUpdates(historyFor(key, stamp))
    setLastSignal(stamp)
    setNow(Date.now())
    if (terminal) frozen.current = true
  }, [key, measuredAt, terminal])

  useEffect(() => {
    if (!updates.length || terminal) return
    const timer = setInterval(() => setNow(Date.now()), HEARTBEAT_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [terminal, updates.length])

  const buckets = retainedHeartbeatHistory(updates, now)
  const total = buckets.reduce((sum, value) => sum + value, 0)
  const max = Math.max(1, ...buckets)
  const age = refreshedAge(lastSignal, now)

  return (
    <span className="live-heartbeat" data-terminal={terminal ? 'true' : 'false'}>
      <span className="live-heartbeat-bars" data-stage={stage} aria-hidden="true"
        title="Snapshot refreshes in four 15-second windows over the last minute">
        {buckets.map((value, index) => (
          <i key={index} data-active={value ? 'true' : 'false'}
             style={{ opacity: value ? Math.max(0.55, value / max) : 0.14 }} />
        ))}
      </span>
      {showText && <span className="live-heartbeat__text">
        {terminal ? 'Final' : 'Live'} · {age}
      </span>}
      <span className="sr-only">{terminal ? 'Final snapshot refresh history' : 'Snapshot refresh history'}, {age}; {total} successful canonical snapshot refresh{total === 1 ? '' : 'es'} in the last 60 seconds. Four slots represent fifteen seconds each; totals are from the canonical snapshot.</span>
    </span>
  )
}

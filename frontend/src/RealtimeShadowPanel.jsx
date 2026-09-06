import { useEffect, useMemo, useRef, useState } from 'react'
import { getRealtimeShadowClient } from './realtimeShadowClient.js'

function differences(current, incoming) {
  if (!incoming || typeof incoming !== 'object') return 0
  return Object.keys(incoming).reduce((count, key) => {
    if (typeof incoming[key] === 'object') return count
    return count + (current?.[key] === incoming[key] ? 0 : 1)
  }, 0)
}

export default function RealtimeShadowPanel({ enabled = false, currentSnapshot, client = getRealtimeShadowClient() }) {
  const [health, setHealth] = useState(client.snapshot())
  const [lastEvent, setLastEvent] = useState(null)
  const [mismatchCount, setMismatchCount] = useState(0)
  const currentSnapshotRef = useRef(currentSnapshot)
  currentSnapshotRef.current = currentSnapshot

  useEffect(() => {
    if (!enabled) return undefined
    const offHealth = client.subscribe(setHealth)
    const offEvent = client.onEvent((event) => {
      setLastEvent(event)
      const snapshot = event.payload?.snapshot
      if (snapshot) setMismatchCount(differences(currentSnapshotRef.current, snapshot))
    })
    client.start()
    return () => { offEvent(); offHealth(); client.stop() }
  }, [client, enabled])

  const latency = useMemo(() => health.latencyMs == null ? 'waiting' : `${health.latencyMs} ms`, [health.latencyMs])
  if (!enabled) return null
  return (
    <aside aria-label="Realtime shadow diagnostics" data-testid="realtime-shadow-panel" style={{ position: 'fixed', right: 12, bottom: 12, zIndex: 1000, width: 270, padding: 12, borderRadius: 8, color: '#E5E7EB', background: '#111827', boxShadow: '0 8px 24px #0005', fontSize: 12 }}>
      <strong>Realtime shadow</strong>
      <dl style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 8px', margin: '8px 0 0' }}>
        <dt>Connection</dt><dd style={{ margin: 0 }}>{health.state}</dd>
        <dt>Event latency</dt><dd style={{ margin: 0 }}>{latency}</dd>
        <dt>Reconnects</dt><dd style={{ margin: 0 }}>{health.reconnects}</dd>
        <dt>UI differences</dt><dd style={{ margin: 0 }}>{mismatchCount}</dd>
        <dt>Last event</dt><dd style={{ margin: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>{lastEvent?.kind || 'none'}</dd>
      </dl>
      {health.state === 'fallback' && <p role="status" style={{ margin: '8px 0 0' }}>Existing live updates remain active.</p>}
    </aside>
  )
}

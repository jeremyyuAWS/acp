import { useEffect, useState } from 'react'
import { freshness } from './remediationSnapshot.js'

// Transport age advances independently of successful polls or snapshot changes.
// The clock never changes receivedAt or pretends a heartbeat is saved progress.
export default function useRemediationFreshness({ snapshot, connected, receivedAt }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const refresh = () => setNow(Date.now())
    refresh()
    const timer = setInterval(refresh, 1000)
    document.addEventListener('visibilitychange', refresh)
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', refresh) }
  }, [])
  return freshness({snapshot,connected,receivedAt,now:Math.max(now,receivedAt || 0)})
}

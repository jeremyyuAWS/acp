import { useEffect, useRef, useState } from 'react'
import { authEpoch } from './apiIdentity.js'
import { drawerMetricScope, getWaterfallDrawerMetrics } from './waterfallDrawerMetricsClient.js'

export default function useWaterfallDrawerMetrics({ scanId, batchId, scope, live = false, enabled = true }) {
  const session = useRef(0)
  const [state, setState] = useState(null)
  const [reload, setReload] = useState(0)
  const [visible, setVisible] = useState(() => !document.hidden)
  const epoch = authEpoch()
  const scopeKey = JSON.stringify(drawerMetricScope(scope))
  const identity = JSON.stringify([epoch, scanId, batchId, scopeKey])
  useEffect(() => {
    const update = () => setVisible(!document.hidden)
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])
  useEffect(() => {
    if (!enabled || !scanId || !batchId || !visible) return
    const baselineSession = ++session.current
    let active = true, timer, controller, denied = false
    const current = () => active && epoch === authEpoch()
    const load = async () => {
      controller = new AbortController()
      setState(previous => ({ ...(previous?.identity === identity ? previous : {}), identity, loading: true }))
      try {
        const data = await getWaterfallDrawerMetrics(scanId, batchId, JSON.parse(scopeKey), controller.signal)
        if (!current()) return
        setState(previous => {
          const before = previous?.identity === identity ? previous : null
          return { identity, data, loading: false, error: false, receivedAt: Date.now(), baseline: `${baselineSession}:${before?.error ? Date.now() : before?.baseline?.split(':')[1] || 0}` }
        })
      } catch (error) {
        if (!current() || error?.name === 'AbortError') return
        denied = [401, 403].includes(error?.status)
        setState(previous => ({ ...(previous?.identity === identity && !denied ? previous : {}), identity, loading: false, error: true, denied }))
      } finally {
        if (current() && live && !denied) timer = setTimeout(load, 15000)
      }
    }
    load()
    return () => { active = false; clearTimeout(timer); controller?.abort() }
  }, [scanId, batchId, scopeKey, identity, epoch, enabled, visible, live, reload])
  return { ...(state?.identity === identity ? state : {}), refresh: () => setReload(value => value + 1) }
}

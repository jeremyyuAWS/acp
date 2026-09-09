import { useEffect, useState } from 'react'
import { authEpoch } from './apiIdentity.js'
import { getRunInsights } from './remediationRunInsightsClient.js'

// One bounded page, fetched only while visible/expanded. This endpoint reads saved history.
export default function useRemediationAttemptStory({ scanId, batchId, open, live = false, paused = false, offset = 0 }) {
  const identity = `${authEpoch()}:${scanId}:${batchId}:${offset}`
  const [state, setState] = useState(null)
  const [reload, setReload] = useState(0)
  const [visible, setVisible] = useState(() => !document.hidden)
  useEffect(() => {
    const update = () => setVisible(!document.hidden)
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])
  useEffect(() => {
    if (!open || paused || !visible || !scanId || !batchId) return undefined
    let active = true
    let timer
    let controller
    const epoch = authEpoch()
    const current = () => active && epoch === authEpoch()
    const load = async () => {
      controller = new AbortController()
      setState(previous => ({ ...(previous?.identity === identity ? previous : {}), identity, loading: true, error: false }))
      try {
        const data = await getRunInsights(scanId, batchId, controller.signal, offset)
        if (!current()) return
        if (data && (data.scan_id !== scanId || data.batch_id !== batchId)) throw new Error('Run changed')
        setState({ identity, data, loading: false, error: false, receivedAt: Date.now() })
      } catch (error) {
        if (current() && error?.name !== 'AbortError') setState(previous => ({ ...(previous?.identity === identity ? previous : {}), identity, loading: false, error: true }))
      } finally {
        if (current() && live) timer = setTimeout(load, 15_000)
      }
    }
    load()
    return () => { active = false; clearTimeout(timer); controller?.abort() }
  }, [scanId, batchId, identity, offset, open, live, paused, visible, reload])
  return { ...(state?.identity === identity ? state : {}), refresh: () => setReload(value => value + 1) }
}

import { useEffect, useState } from 'react'
import { authEpoch } from './apiIdentity.js'
import { getWaterfall } from './remediationWaterfallClient.js'

export default function useWaterfallActivity(scanId, batchId, paused) {
  const identity = `${authEpoch()}:${scanId}:${batchId}`
  const [state, setState] = useState(null)
  useEffect(() => {
    if (!scanId || !batchId || paused) return undefined
    let cancelled = false
    let timer
    const controller = new AbortController()
    const load = async () => {
      try {
        const view = await getWaterfall(scanId, batchId, controller.signal)
        if (!cancelled) setState({ identity, view, error: false })
      } catch {
        if (!cancelled) setState(old => ({ identity, view: old?.identity === identity ? old.view : null, error: true }))
      } finally {
        if (!cancelled) timer = setTimeout(load, 5000)
      }
    }
    load()
    return () => { cancelled = true; controller.abort(); clearTimeout(timer) }
  }, [scanId, batchId, identity, paused])
  return state?.identity === identity ? state : { view: null, error: false }
}

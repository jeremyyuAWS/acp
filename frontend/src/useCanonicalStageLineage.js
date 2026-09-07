import { useCallback, useEffect, useRef, useState } from 'react'

const POLL_MS = 15_000

function lineageVersion(value) {
  const lineage = value?.lineage || value
  const stageRevision = Math.max(0, ...(lineage?.stages || []).map((stage) => Number(stage.revision || 0)))
  return [Number(lineage?.workflow_revision || 0), stageRevision]
}

export function isNewerLineage(previous, next) {
  if (!next) return false
  if (!previous) return true
  const [previousWorkflow, previousStage] = lineageVersion(previous)
  const [nextWorkflow, nextStage] = lineageVersion(next)
  return nextWorkflow > previousWorkflow
    || (nextWorkflow === previousWorkflow && nextStage >= previousStage)
}

export function useCanonicalStageLineage(scanId, loadLineage) {
  const [result, setResult] = useState(null)
  const [receivedAt, setReceivedAt] = useState(null)
  const latest = useRef(null)

  const accept = useCallback((next) => {
    if (!isNewerLineage(latest.current, next)) return
    latest.current = next
    setResult(next)
    setReceivedAt(Date.now())
  }, [])

  useEffect(() => {
    latest.current = null
    setResult(null)
    setReceivedAt(null)
    if (!scanId || typeof loadLineage !== 'function') return undefined

    let live = true
    const refresh = () => {
      if (!live || document.hidden) return
      loadLineage(scanId).then((next) => { if (live) accept(next) }).catch(() => {})
    }
    const stop = () => { live = false }
    refresh()
    const poll = setInterval(refresh, POLL_MS)
    window.addEventListener('focus', refresh)
    window.addEventListener('acp:session-expired', stop)
    return () => {
      live = false
      clearInterval(poll)
      window.removeEventListener('focus', refresh)
      window.removeEventListener('acp:session-expired', stop)
    }
  }, [scanId, loadLineage, accept])

  return { lineage: result?.lineage || result, contentDigest: result?.content_digest || null,
    receivedAt }
}

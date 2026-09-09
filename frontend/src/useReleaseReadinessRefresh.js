import { useEffect, useRef } from 'react'
import { getScan } from './api.js'

export default function useReleaseReadinessRefresh({ runId, enabled, surface, snapshot, events = [], onScan }) {
  const onScanRef = useRef(onScan)
  onScanRef.current = onScan
  const requestRef = useRef(null)
  const matching = (snapshot?.scan_id || snapshot?.run_id) === runId
  // Heartbeats/revision timestamps are deliberately excluded: only recorded material work
  // can change which corrected files are releasable. The read still checks actual file rows.
  const signal = JSON.stringify(matching ? [snapshot.documents, snapshot.fixes, snapshot.delivery,
    snapshot.review, snapshot.terminal, events.find(event => event.material !== false)?.id] : null)
  useEffect(() => {
    if (!runId || !enabled) return
    let live = true, timer, pending = false, queued = false, lastRead = -Infinity
    const request = () => {
      if (!live) return
      queued = true
      if (pending || timer) return
      timer = setTimeout(async () => {
        timer = null; pending = true; queued = false; lastRead = Date.now()
        try {
          const scan = await getScan(runId)
          if (live && scan?.run?.id === runId) onScanRef.current(scan)
        } catch { if (live) queued = true }
        finally { pending = false; if (live && queued) request() }
      }, Math.max(0, 5000 - (Date.now() - lastRead)))
    }
    requestRef.current = request
    request() // Opening Release must not wait for the next event or whole-run completion.
    return () => { live = false; clearTimeout(timer); requestRef.current = null }
  }, [runId, enabled, surface])
  useEffect(() => { if (enabled && matching) requestRef.current?.() }, [signal, enabled, matching])
}

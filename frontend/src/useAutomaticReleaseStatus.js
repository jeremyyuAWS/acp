import { useEffect } from 'react'
import { getAutomaticRelease } from './api.js'
import { authEpoch } from './apiIdentity.js'

// Read-only observer retained after retiring the embedded publication panel.
// Publication is authorized and performed by durable server jobs, never this hook.
export default function useAutomaticReleaseStatus(scanId, files, onStatus, get = getAutomaticRelease) {
  const scope = [...new Set(files.map(file => typeof file === 'string' ? file : file.file).filter(Boolean))].sort()
  const key = JSON.stringify([scanId, scope, authEpoch()])
  useEffect(() => {
    let live = true, timer, cancel
    const epoch = authEpoch()
    const controller = new AbortController()
    onStatus({ scanId, runId: undefined, authorization: undefined })
    if (!scanId) return () => controller.abort()
    async function load() {
      let deadline
      try {
        const result = await Promise.race([
          get(scanId, scope, { signal: controller.signal }),
          new Promise((_, reject) => {
            cancel = () => reject(new Error('Status request cancelled'))
            deadline = setTimeout(() => { controller.abort(); reject(new Error('Status request timed out')) }, 20000)
          }),
        ])
        if (!live || authEpoch() !== epoch) return
        onStatus({ scanId, runId: result?.run_id, authorization: result?.authorization })
      } catch (error) {
        if (!live || authEpoch() !== epoch || controller.signal.aborted || [401, 403, 404].includes(error?.status)) return
      } finally { clearTimeout(deadline); cancel = null }
      if (live && authEpoch() === epoch) timer = setTimeout(load, 5000)
    }
    load()
    return () => { live = false; clearTimeout(timer); controller.abort(); cancel?.() }
  }, [key, onStatus, get])
}

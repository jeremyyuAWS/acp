import { useEffect, useRef, useState } from 'react'
import { getRunAiApproval, setRunAiApproval } from './api.js'
import { authEpoch } from './apiIdentity.js'

const REQUEST_TIMEOUT = 20000

export default function useRunAiApproval(scanId, runId) {
  const [setting, setSetting] = useState(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState(null)
  const [reload, setReload] = useState(0)
  const epoch = authEpoch()
  const identity = `${epoch}:${scanId || ''}:${runId || ''}`
  const identityRef = useRef(identity)
  identityRef.current = identity
  const writing = useRef(false)
  const requests = useRef(new Set())
  const generation = useRef(0)
  const currentScope = (scope, stamp, version) => identityRef.current === scope && authEpoch() === stamp && generation.current === version
  const bounded = async operation => {
    const controller = new AbortController()
    let timer, cancel
    const deadline = new Promise((resolve, reject) => {
      cancel = () => { controller.abort(); reject(new DOMException('Request cancelled', 'AbortError')) }
      timer = window.setTimeout(() => {
        controller.abort()
        reject(new Error('Automatic approval took too long to respond. Refresh the setting to try again.'))
      }, REQUEST_TIMEOUT)
    })
    requests.current.add(cancel)
    try { return await Promise.race([Promise.resolve().then(() => operation(controller.signal)), deadline]) }
    finally { window.clearTimeout(timer); requests.current.delete(cancel) }
  }
  useEffect(() => {
    const version = ++generation.current
    setSetting(null); setSaving(false); setError(''); setNotice(null); writing.current = false
    if (scanId && runId) bounded(signal => getRunAiApproval(scanId, runId, { signal })).then(result => {
      if (currentScope(identity, epoch, version)) setSetting({ ...result, identity })
    }).catch(() => {
      if (currentScope(identity, epoch, version)) setError('Automatic approval setting is unavailable. Refresh the setting to try again.')
    })
    return () => {
      generation.current += 1
      for (const cancel of [...requests.current]) cancel()
    }
  }, [identity, reload])
  const current = setting?.identity === identity && authEpoch() === epoch ? setting : null
  const change = current && current.supported !== false ? async enabled => {
    if (writing.current || authEpoch() !== epoch) return
    const version = generation.current
    writing.current = true; setSaving(true); setError(''); setNotice(null)
    try {
      const result = await bounded(signal => setRunAiApproval(scanId, runId, { enabled, expected_revision: current.revision,
        expected_source_revision: current.source_revision }, { signal }))
      if (currentScope(identity, epoch, version)) {
        setSetting({ ...result, identity })
        if (enabled && result?.enabled === true && result.supported !== false) setNotice({identity})
      }
    } catch (failure) {
      if (currentScope(identity, epoch, version)) {
        setError(failure.message || 'Automatic approval could not be saved.')
        try {
          // A lost save response is uncertain. Read the durable setting, never replay the POST.
          const latest = await bounded(signal => getRunAiApproval(scanId, runId, { signal }))
          if (currentScope(identity, epoch, version)) setSetting({ ...latest, identity })
        } catch { /* Keep the last confirmed value while reporting the failed save. */ }
      }
    } finally {
      if (currentScope(identity, epoch, version)) { writing.current = false; setSaving(false) }
    }
  } : undefined
  return { notice: notice?.identity === identity && authEpoch() === epoch ? notice : null, dismissNotice: () => setNotice(null), policy: current, enabled: current?.enabled ?? null, saving, error: error || (current?.supported === false ? current.reason : ''), change,
    retry: () => { if (!writing.current) setReload(value => value + 1) } }
}

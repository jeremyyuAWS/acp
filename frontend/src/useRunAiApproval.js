import { useEffect, useRef, useState } from 'react'
import { getRunAiApproval, setRunAiApproval } from './api.js'

export default function useRunAiApproval(scanId, runId) {
  const [setting, setSetting] = useState(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const identity = `${scanId || ''}:${runId || ''}`
  const identityRef = useRef(identity)
  identityRef.current = identity
  const writing = useRef(false)
  useEffect(() => {
    let active = true
    setSetting(null); setSaving(false); setError(''); writing.current = false
    if (scanId && runId) Promise.resolve().then(() => getRunAiApproval(scanId, runId)).then(result => {
      if (active) setSetting({ ...result, identity })
    }).catch(() => { if (active) setError('Automatic approval setting is unavailable. Refresh to try again.') })
    return () => { active = false }
  }, [identity])
  const current = setting?.identity === identity ? setting : null
  const change = current && current.supported !== false ? async enabled => {
    if (writing.current) return
    writing.current = true; setSaving(true); setError('')
    try {
      const result = await setRunAiApproval(scanId, runId, { enabled, expected_revision: current.revision,
        expected_source_revision: current.source_revision })
      if (identityRef.current === identity) setSetting({ ...result, identity })
    } catch (failure) {
      if (identityRef.current === identity) {
        setError(failure.message || 'Automatic approval could not be saved.')
        try {
          const latest = await getRunAiApproval(scanId, runId)
          if (identityRef.current === identity) setSetting({ ...latest, identity })
        } catch { /* Keep the last confirmed value while reporting the failed save. */ }
      }
    } finally {
      if (identityRef.current === identity) { writing.current = false; setSaving(false) }
    }
  } : undefined
  return { policy: current, enabled: current?.enabled ?? null, saving, error: error || (current?.supported === false ? current.reason : ''), change }
}

import { useEffect, useRef, useState } from 'react'
import { getRemediationAutomationPolicy, submitRemediationPolicyAction } from './api.js'

const newKey = () => globalThis.crypto?.randomUUID?.() || `policy-${Date.now()}-${Math.random()}`

/** Narrow Phase-4 seam: the preview owns layout/forecast; this component owns commands only. */
export default function AutomationPolicyActions({ runId, previewLevel, onReset }) {
  const [contract, setContract] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const pendingKey = useRef(null)
  const feedback = useRef(null)

  useEffect(() => {
    let live = true
    setError('')
    if (!runId) return () => { live = false }
    getRemediationAutomationPolicy(runId)
      .then((value) => { if (live) setContract(value) })
      .catch((err) => { if (live) setError(err.message || 'The policy could not be loaded.') })
    return () => { live = false }
  }, [runId])

  useEffect(() => { if (error || message) feedback.current?.focus() }, [error, message])

  const submit = async (action) => {
    if (!contract || busy) return
    setBusy(true); setError(''); setMessage('')
    pendingKey.current ||= newKey()
    try {
      const result = await submitRemediationPolicyAction(
        runId, action, previewLevel, contract.policy.revision, pendingKey.current)
      pendingKey.current = null
      setContract((old) => ({ ...old, policy: result.policy }))
      setMessage(action === 'save_future'
        ? 'Saved for future remediation runs. This run was not changed.'
        : 'Eligible waiting work now uses this policy snapshot.')
    } catch (err) {
      // Preserve the key for an uncertain transport/server outcome; a retry can cause at most
      // one effect. A proven conflict made no change and must be reconciled before retrying.
      if (err.status && err.status < 500) pendingKey.current = null
      setError(typeof err.detail === 'object' ? (err.detail.message || err.message) : err.message)
    } finally { setBusy(false) }
  }

  const reset = () => {
    pendingKey.current = null; setError(''); setMessage('Preview reset to the saved policy.')
    onReset(contract?.policy?.level ?? 3)
  }

  return <div className="automation-policy__actions" aria-label="Automation policy actions">
    <button type="button" disabled={!contract || busy || previewLevel === contract?.policy?.level}
      onClick={() => submit('save_future')}>Save for future runs</button>
    {contract?.capabilities?.apply_waiting &&
      <button type="button" disabled={busy} onClick={() => submit('apply_waiting')}>
        Apply to eligible waiting work
      </button>}
    <button type="button" disabled={!contract || busy || previewLevel === contract?.policy?.level}
      onClick={reset}>Reset preview</button>
    {(error || message) && <p ref={feedback} tabIndex="-1" role={error ? 'alert' : 'status'}>
      {error || message}
    </p>}
  </div>
}

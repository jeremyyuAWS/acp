import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import './release-recovery-banner.css'

export default function ReleaseRecoveryBanner({ status, providerName, error, onReconnect, onCheckStatus, disabled }) {
  const [offset, setOffset] = useState(0)
  useEffect(() => {
    const measure = () => setOffset(document.querySelector('[aria-label="Dismiss version notification"]')?.parentElement?.getBoundingClientRect().height || 0)
    measure()
    const observer = new MutationObserver(measure)
    observer.observe(document.body, { childList: true, subtree: true })
    window.addEventListener('resize', measure)
    return () => { observer.disconnect(); window.removeEventListener('resize', measure) }
  }, [])
  if (status === 'idle') return null
  const signIn = status === 'sign_in'
  const unconfirmed = status === 'unconfirmed'
  return createPortal(<div className={`release-recovery-banner ${signIn || unconfirmed ? 'release-recovery-banner--attention' : ''}`}
    role="status" aria-live="polite" style={{ top: offset }}>
    <span><strong>{signIn ? `${providerName} sign-in is required` : unconfirmed ? 'Delivery recovery is unconfirmed' : status === 'recovering' ? 'Recovering saved delivery automatically' : 'Checking saved delivery status'}</strong>
      <span>{signIn ? ' Reconnect to continue this saved release. Existing delivered copies are checked first; no new scan or approval is needed.' : unconfirmed ? ' ACP is refreshing the saved status. Delivery has not been confirmed; another request will not be sent without fresh recovery evidence.' : ' ACP checks existing copies before continuing. No extra approval is needed.'}</span>
      {error && <span className="release-recovery-banner__detail">{error}</span>}
    </span>
    {unconfirmed && <button type="button" disabled={disabled} onClick={onCheckStatus}>Check delivery status</button>}
    {signIn && <button type="button" disabled={disabled} onClick={onReconnect}>Reconnect {providerName} and resume delivery</button>}
  </div>, document.body)
}

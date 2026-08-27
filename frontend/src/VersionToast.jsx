import { useState, useEffect, useRef } from 'react'
import { getConfig } from './api'

const POLL_MS = 10 * 60 * 1000  // 10 minutes

// Full-width top banner that appears when the server version advances past the version the page
// loaded with. Polls /config (public, pre-auth endpoint) on an interval so it works across
// long sessions. Uses baseRef so the poll closure never captures a stale version string.

export function VersionToastBanner({ onReload, onDismiss }) {
  return (
    <div role="status" aria-live="polite"
         style={{
           position: 'fixed', top: 0, left: 0, right: 0,
           background: '#16a34a',
           color: '#fff',
           padding: '10px 16px',
           display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 14,
           boxShadow: '0 2px 8px rgba(0,0,0,.18)',
           zIndex: 9999,
           fontSize: 14,
           fontWeight: 500,
         }}>
      <span>✦ A new version of ACP is available.</span>
      <button type="button"
              onClick={onReload}
              style={{
                background: '#fff', color: '#15803d', border: 'none',
                borderRadius: 6, padding: '4px 14px', fontWeight: 650,
                fontSize: 13, cursor: 'pointer',
              }}>
        Reload now
      </button>
      <button type="button" onClick={onDismiss}
              aria-label="Dismiss version notification"
              style={{
                position: 'absolute', right: 14, top: '50%', transform: 'translateY(-50%)',
                background: 'transparent', border: 'none', color: 'rgba(255,255,255,.8)',
                fontSize: 18, cursor: 'pointer', lineHeight: 1, padding: '2px 4px',
              }}>✕</button>
    </div>
  )
}

export default function VersionToast({ currentVersion }) {
  const [show, setShow] = useState(false)
  const baseRef = useRef(currentVersion)

  useEffect(() => {
    // Don't start polling until we know what version the page loaded with.
    if (!baseRef.current) return
    const t = setInterval(() => {
      getConfig().then((c) => {
        if (c?.version && c.version !== baseRef.current) setShow(true)
      }).catch(() => {})
    }, POLL_MS)
    return () => clearInterval(t)
  }, [])

  if (!show) return null
  return (
    <VersionToastBanner
      onReload={() => window.location.reload()}
      onDismiss={() => setShow(false)}
    />
  )
}

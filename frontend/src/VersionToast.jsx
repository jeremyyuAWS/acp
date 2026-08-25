import { useState, useEffect, useRef } from 'react'
import { getConfig } from './api'

const POLL_MS = 10 * 60 * 1000  // 10 minutes

// Fixed toast that appears when the server version advances past the version the page loaded with.
// Polls /config (public, pre-auth endpoint) on an interval so it works across long sessions.
// Uses baseRef so the poll closure never captures a stale version string.

export function VersionToastBanner({ onReload, onDismiss }) {
  return (
    <div role="status" aria-live="polite"
         style={{
           position: 'fixed', bottom: 20, right: 20,
           background: 'var(--panel, #fff)',
           border: '1px solid var(--line, #e4e8ec)',
           borderRadius: 10,
           padding: '10px 14px',
           display: 'flex', alignItems: 'center', gap: 12,
           boxShadow: '0 4px 16px rgba(0,0,0,.12)',
           zIndex: 9999,
           fontSize: 13.5,
           color: 'var(--ink)',
         }}>
      <span>New version available</span>
      <button type="button" className="primary small" onClick={onReload}>Reload</button>
      <button type="button" className="ghost small" onClick={onDismiss}
              aria-label="Dismiss version notification">✕</button>
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

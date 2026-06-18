import { useEffect } from 'react'

// Shared right slide-out shell: overlay + panel + Esc/overlay/✕ to close.
export default function Drawer({ title, subtitle, onClose, children }) {
  useEffect(() => {
    const k = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  return (
    <div className="drawer-overlay" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={typeof title === 'string' ? title : 'details'} onClick={(e) => e.stopPropagation()}>
        <div className="drawerhead">
          <div style={{ minWidth: 0 }}>
            <div className="fname" style={{ fontSize: 15 }}>{title}</div>
            {subtitle && <div className="muted" style={{ marginTop: 4 }}>{subtitle}</div>}
          </div>
          <button className="ghost small" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        {children}
      </aside>
    </div>
  )
}

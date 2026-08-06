import { useEffect, useRef } from 'react'

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

// Shared right slide-out shell: overlay + panel + Esc/overlay/✕ to close.
// Traps Tab focus inside the panel and restores focus to the trigger on close
// (WCAG 2.4.3 — focus order / no focus loss).
export default function Drawer({ title, subtitle, onClose, children }) {
  const panelRef = useRef(null)
  const prevFocus = useRef(null)
  useEffect(() => {
    prevFocus.current = document.activeElement
    const panel = panelRef.current
    const list = () => [...(panel?.querySelectorAll(FOCUSABLE) || [])].filter((el) => !el.disabled && el.offsetParent !== null)
    ;(list()[0] || panel)?.focus()
    const k = (e) => {
      if (e.key === 'Escape') { onClose(); return }
      if (e.key !== 'Tab') return
      const f = list(); if (!f.length) return
      const i = f.indexOf(document.activeElement)
      if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus() }
      else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus() }
    }
    window.addEventListener('keydown', k)
    return () => { window.removeEventListener('keydown', k); prevFocus.current?.focus?.() }
  }, [onClose])
  return (
    <div className="drawer-overlay" onClick={onClose}>
      <aside ref={panelRef} tabIndex={-1} className="drawer" role="dialog" aria-modal="true" aria-label={typeof title === 'string' ? title : 'details'} onClick={(e) => e.stopPropagation()}>
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

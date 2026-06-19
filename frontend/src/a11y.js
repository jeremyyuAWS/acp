import { useEffect } from 'react'

// True when the user has asked the OS for reduced motion. Used to stop auto-
// advancing carousels/feeds (WCAG 2.2.2 Pause, Stop, Hide / 2.3.3 Animation).
export const prefersReducedMotion = () =>
  typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

// Modal dialog a11y: move focus into the panel on open, trap Tab inside it, close on
// Escape, and restore focus to the trigger on close (WCAG 2.4.3 focus order, 2.1.2 no
// keyboard trap, 4.1.2). Pass a ref to the dialog panel and the close handler.
export function useDialog(panelRef, onClose) {
  useEffect(() => {
    const prev = document.activeElement
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
    return () => { window.removeEventListener('keydown', k); prev?.focus?.() }
  }, [panelRef, onClose])
}

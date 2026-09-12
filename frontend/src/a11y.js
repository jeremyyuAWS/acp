import { useEffect, useRef } from 'react'

// True when the user has asked the OS for reduced motion. Used to stop auto-
// advancing carousels/feeds (WCAG 2.2.2 Pause, Stop, Hide / 2.3.3 Animation).
export const prefersReducedMotion = () =>
  typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

// Modal dialog a11y: move focus into the panel on open, trap Tab inside it, close on
// Escape, and restore focus to the trigger on close (WCAG 2.4.3 focus order, 2.1.2 no
// keyboard trap, 4.1.2). Pass a ref to the dialog panel and the close handler.
export function useDialog(panelRef, onClose) {
  const onCloseRef = useRef(onClose)
  useEffect(() => { onCloseRef.current = onClose }, [onClose])
  useEffect(() => {
    const prev = document.activeElement
    const panel = panelRef.current
    const list = () => [...(panel?.querySelectorAll(FOCUSABLE) || [])].filter((el) => !el.disabled && el.offsetParent !== null)
    ;(list()[0] || panel)?.focus()
    const k = (e) => {
      if (e.key === 'Escape') { onCloseRef.current(); return }
      if (e.key !== 'Tab') return
      const f = list(); if (!f.length) return
      const i = f.indexOf(document.activeElement)
      if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus() }
      else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus() }
    }
    window.addEventListener('keydown', k)
    return () => { window.removeEventListener('keydown', k); prev?.focus?.() }
  }, [panelRef])
}

// Native <details> menus do not dismiss themselves after opening. Keep transient identity
// information from lingering over the workspace, while never closing it under a user who is
// pointing at the panel or tabbing through its actions.
export const ACCOUNT_MENU_DISMISS_MS = 2000

export function useAutoDismissDetails(detailsRef, delayMs = 5000) {
  const binding = useRef(null)
  // Account controls can appear after authentication. Bind when the node arrives,
  // without restarting its timer on every background data refresh.
  useEffect(() => {
    const details = detailsRef.current
    if (binding.current?.node === details && binding.current?.delay === delayMs) return
    binding.current?.dispose()
    binding.current = null
    if (!details) return
    let timer = null
    let focused = false
    const clear = () => { if (timer !== null) clearTimeout(timer); timer = null }
    const arm = () => {
      clear()
      if (details.open && !focused) timer = setTimeout(() => { details.open = false }, delayMs)
    }
    const onToggle = () => { if (details.open) arm(); else clear() }
    const onFocusIn = event => {
      focused = !!event.target.closest?.('.header-menu-panel')
      arm()
    }
    const onFocusOut = event => {
      focused = details.contains(event.relatedTarget) && !!event.relatedTarget?.closest?.('.header-menu-panel')
      arm()
    }
    const events = { toggle: onToggle, pointerenter: arm, pointermove: arm, pointerleave: arm,
      focusin: onFocusIn, focusout: onFocusOut }
    Object.entries(events).forEach(([name, handler]) => details.addEventListener(name, handler))
    binding.current = {node: details, delay: delayMs, dispose: () => {
      clear()
      Object.entries(events).forEach(([name, handler]) => details.removeEventListener(name, handler))
    }}
    arm()
  })
  useEffect(() => () => { binding.current?.dispose(); binding.current = null }, [])
}

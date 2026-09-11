import { useEffect, useId, useRef, useState } from 'react'
import './info-tip.css'

// Secondary copy folded behind a circled "i", so a step states its decision in one line and the
// qualification stays one keystroke away instead of competing with it.
//
// Deliberately NOT the `title` attribute the wizard reached for previously. A native tooltip never
// appears on keyboard focus, so that pattern hides the text from exactly the users who cannot
// hover — in an accessibility product. This is a real button: it opens on hover AND on focus,
// closes on Escape, and is announced through aria-describedby rather than duplicated into an
// off-screen span.
//
// `label` names what the text is about ("About subfolders"), because "more information" tells a
// screen-reader user nothing about which of several tips they have landed on.
export default function InfoTip({ label, children, toggleOnClick = true }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const wrap = useRef(null)
  useEffect(() => {
    if (!open) return
    const onKey = event => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])
  return <span className="info-tip" ref={wrap}
    onMouseEnter={() => setOpen(true)}
    onMouseLeave={() => { if (!wrap.current?.contains(document.activeElement)) setOpen(false) }}>
    <button type="button" aria-label={`About ${label}`} aria-expanded={open}
      aria-describedby={open ? id : undefined}
      onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
      onClick={() => setOpen(v => toggleOnClick ? !v : true)}>
      <span aria-hidden="true">i</span>
    </button>
    {open && <span id={id} role="tooltip" className="info-tip__text">{children}</span>}
  </span>
}

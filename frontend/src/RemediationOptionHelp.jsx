import './tooltip-typography.css'
import { useEffect, useId, useState } from 'react'
import './remediation-option-help.css'

export default function RemediationOptionHelp({ label, children }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return
    const dismiss = event => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', dismiss)
    return () => document.removeEventListener('keydown', dismiss)
  }, [open])
  return <div className="remediation-option-help"
    onMouseEnter={() => setOpen(true)}
    onMouseLeave={event => { if (!event.currentTarget.contains(document.activeElement)) setOpen(false) }}>
    <button type="button" aria-label={`About ${label}`} aria-describedby={open ? id : undefined}
      onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
      onClick={() => setOpen(true)}
      onKeyDown={event => { if (event.key === 'Escape') { setOpen(false); event.stopPropagation() } }}>
      <span aria-hidden="true">i</span>
    </button>
    {open && <div id={id} role="tooltip" className="remediation-option-help__text">{children}</div>}
  </div>
}

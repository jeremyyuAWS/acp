import { useId, useRef, useState } from 'react'
import { GLOSSARY } from './glossary.js'

// An inline glossary tooltip for a KPI label or term that reads as jargon out of context — e.g.
// wrap "could not be read" with <Term k="unreadable">could not be read</Term> and a small info
// affordance appears beside it.
//
// Built as a real hover+focus tooltip, not a native `title` attribute: `title` has no keyboard
// trigger, shows on a browser-controlled delay outside CSS's control, and screen-reader support
// is inconsistent — all three matter more than usual on a product whose whole job is making
// content perceivable to people who don't use a mouse. `aria-describedby` links the trigger to
// the definition; the definition itself is `role="tooltip"`, shown on hover OR focus, and
// dismissible with Escape — the shape the WAI-ARIA tooltip pattern describes.
//
// An unrecognized key renders the label plainly, never a crash — a typo'd glossary key should
// degrade to "no tooltip", the same failure mode as forgetting to wrap the label at all.
export default function Term({ k, children }) {
  const entry = GLOSSARY[k]
  const [open, setOpen] = useState(false)
  const id = useId()
  const hideTimer = useRef(null)

  if (!entry) return children

  const show = () => { clearTimeout(hideTimer.current); setOpen(true) }
  // A short delay, not instant close, so moving the mouse from the trigger toward the box itself
  // (both inside this same wrapper) doesn't flicker the tooltip shut mid-transit.
  const hide = () => { hideTimer.current = setTimeout(() => setOpen(false), 80) }

  return (
    <span className="term" onMouseLeave={hide}>
      {children}
      <button type="button" className="terminfo" aria-label={`What does "${entry.term}" mean?`}
              aria-describedby={open ? id : undefined} aria-expanded={open}
              onMouseEnter={show} onFocus={show} onBlur={hide}
              onKeyDown={(e) => { if (e.key === 'Escape') setOpen(false) }}>
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.4" />
          <circle cx="8" cy="4.6" r="0.9" fill="currentColor" />
          <path d="M8 7.2v4.6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <span role="tooltip" id={id} className="termbox">
          <b>{entry.term}</b>
          <span>{entry.body}</span>
        </span>
      )}
    </span>
  )
}

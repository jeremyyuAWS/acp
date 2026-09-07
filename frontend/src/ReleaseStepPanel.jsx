import { useEffect, useRef } from 'react'
import './release-accessibility.css'

/**
 * Accessible boundary for one view of the Release builder.
 *
 * `focusOnMount` should be true only after an operator-initiated step change. Keeping it false
 * for the initial file-selection view prevents Release from stealing focus when the tab opens.
 */
export default function ReleaseStepPanel({
  children,
  className = '',
  focusOnMount = false,
  heading,
  id,
}) {
  const panelRef = useRef(null)
  const headingId = `${id}-heading`

  useEffect(() => {
    if (!focusOnMount) return undefined
    const frame = window.requestAnimationFrame(() => panelRef.current?.focus({ preventScroll: true }))
    return () => window.cancelAnimationFrame(frame)
  }, [focusOnMount])

  return (
    <section
      ref={panelRef}
      id={id}
      className={`release-step-panel${className ? ` ${className}` : ''}`}
      role="group"
      aria-labelledby={headingId}
      tabIndex={-1}
    >
      <h3 id={headingId} className="release-step-panel__heading">{heading}</h3>
      {children}
    </section>
  )
}

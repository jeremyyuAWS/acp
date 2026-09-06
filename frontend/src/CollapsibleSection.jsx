import { useState } from 'react'

/**
 * A Live Operations panel that folds away, reusing the panel's OWN header as the control.
 *
 * Native <details>/<summary>, not a div with aria-expanded: the disclosure is then keyboard- and
 * screen-reader-correct with no ARIA of our own, browsers that expand-on-find can still find text
 * inside it, and a closed section is genuinely not rendered rather than clipped to zero height.
 *
 * The caller passes its existing header as `summary` rather than a title string, so the heading
 * appears ONCE. Wrapping a panel in an outer disclosure with its own title was the obvious first
 * shape and it renders the name twice, in two nested bordered boxes.
 *
 * NOTHING IS REMOVED BY COLLAPSING. These panels are why the page exists; they simply do not all
 * have to be open between the summary tiles and the map.
 *
 * The reader's choice is remembered per browser. localStorage is wrapped because reading it
 * THROWS rather than returning null in a private window or with site data blocked, and a
 * preference that cannot be read must fall back to the default, never break the page.
 */
export default function CollapsibleSection({
  id, summary, label, defaultOpen = false, children, style = {},
}) {
  const key = `acp.liveops.section.${id}`
  const [open, setOpen] = useState(() => {
    try {
      const held = window.localStorage.getItem(key)
      if (held === '0' || held === '1') return held === '1'
    } catch { /* private window or blocked site data — use the default */ }
    return defaultOpen
  })
  const remember = (next) => {
    setOpen(next)
    try { window.localStorage.setItem(key, next ? '1' : '0') } catch { /* nowhere to remember it */ }
  }
  return <details className="panel" aria-label={label} open={open}
    onToggle={(event) => remember(event.currentTarget.open)}
    style={{ padding: 12, marginBottom: 12, ...style }}>
    {/* `list-item` keeps the native disclosure triangle, which is the non-colour cue that this
        is expandable (WCAG 1.4.1) and the thing a reader already knows how to operate. */}
    <summary style={{ cursor: 'pointer', display: 'list-item' }}>{summary}</summary>
    {children}
  </details>
}

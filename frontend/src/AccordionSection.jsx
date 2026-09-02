import { useId, useState } from 'react'

/**
 * A disclosure ("accordion") section, built to the WAI-ARIA APG accordion pattern.
 *
 * The whole header is a real <button> inside the section heading, so it is in the tab
 * order, operates on Enter and Space without any key handling of our own, and picks up
 * the global :focus-visible ring (styles.css) plus the .acc-toggle rule beside it.
 *
 * The panel element is ALWAYS rendered so `aria-controls` never points at a missing id;
 * its children are unmounted while collapsed so a hidden section cannot contribute text
 * to a screen's accessible name, to a snapshot, or to a test that reads textContent.
 *
 * `id` must be stable and unique on the screen — it is the visible anchor for both ids,
 * with a React-generated suffix so two instances of the same section (Overview and a
 * drawer, say) still cannot collide.
 */
export default function AccordionSection({
  id,
  title,
  meta = null,
  defaultOpen = true,
  actions = null,
  className = 'panel',
  style,
  ariaLabel,
  children,
}) {
  const [open, setOpen] = useState(defaultOpen)
  const uid = useId()
  const headerId = `acc-${id}-h${uid}`
  const panelId = `acc-${id}-p${uid}`
  return (
    <section className={className} style={style} aria-label={ariaLabel} data-accordion={id}>
      <div className="acc-head">
        <h2 className="acc-heading" style={{ margin: 0, flex: '1 1 auto', minWidth: 0 }}>
          <button type="button"
                  id={headerId}
                  className="acc-toggle"
                  aria-expanded={open}
                  aria-controls={panelId}
                  onClick={() => setOpen((o) => !o)}>
            <span className="acc-chevron" aria-hidden="true">{open ? '▾' : '▸'}</span>
            <span className="acc-title">{title}</span>
            {meta != null && <span className="muted acc-meta"> · {meta}</span>}
          </button>
        </h2>
        {actions}
      </div>
      {/* No `role="region"` on the panel. The APG says to omit it once a screen carries more than
          about six panels — Overview carries seven — and the enclosing <section aria-label> is
          already a region with the same name, so adding one here nests two identically-named
          landmarks inside each other. That is noise for a screen-reader user, and it made the
          Playwright spec's `getByRole('region', { name: 'Estate overview' })` ambiguous, which is
          how it was found. `aria-labelledby` stays: it names the element `aria-controls` points at
          without inventing a second landmark. */}
      <div id={panelId}
           aria-labelledby={headerId}
           className="acc-panel"
           hidden={!open}>
        {open && children}
      </div>
    </section>
  )
}

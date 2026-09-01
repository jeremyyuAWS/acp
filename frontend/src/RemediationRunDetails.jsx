import { useId, useState } from 'react'

// Run details — the progressive-disclosure shell for the redesigned Remediate tab.
//
// The reviewer's job on this tab is a DECISION per finding. Everything that is not that decision —
// reviewer analytics, AI quality, delivery, engine internals, worker queue, business risk, audit
// history, closeout — is real and is needed, but it is needed by someone who has come looking for
// it, not by the person working the queue. Eight panels stacked above the work is how a reviewer
// scrolls past the same reference material on every single finding. This is where those panels
// go, so they stay reachable without standing between the reviewer and the next call.
//
// THE ONE THING THIS MUST NOT DO IS HIDE A FAILURE. Progressive disclosure buys quiet by making
// content cost a click, and that trade is wrong for a blocking error: a verification failure the
// reviewer never sees is worse than eight panels they scroll past. So `alert: true` sections are
// EXEMPT — they render above the toggle, always, collapsed surface or not, and the toggle itself
// carries a written count so the exception is legible before it is opened. That count is words,
// not a red dot: this is a product that certifies accessibility, and a state signalled by colour
// alone (WCAG 1.4.1) would be a defect shipped by the screen that reports defects.
//
// <details>/<summary> for the individual sections rather than button + state, for the reason
// RemSection in Remediate.jsx gives: it is natively keyboard-operable and announces its own
// expanded state, so there is no focus handling and no aria-expanded to keep in sync. The TOP
// toggle cannot be a <details> — alert sections have to escape it and live outside the disclosure
// — so that one is a real <button> and carries aria-expanded/aria-controls by hand.

/**
 * Is there anything to disclose? A section whose children is null/undefined/false is skipped
 * entirely rather than rendered as an empty <details>. An empty disclosure is worse than a missing
 * one: it costs the reader a click to learn that there was nothing behind it, and it does that
 * every time. Callers pass the same expression that decides whether the panel has content at all.
 *
 * Deliberately not falsy-testing: 0 and '' are legitimate ReactNodes, and a section whose body is
 * the number 0 is content. Only the three "there is nothing here" values are skipped.
 */
const hasBody = (c) => c !== null && c !== undefined && c !== false

/**
 * A blocking section, rendered OUTSIDE the disclosure and above the toggle.
 *
 * Plain <section> rather than <details>: the requirement is that a blocking failure is READ, and
 * an alert behind a summary the reviewer has to open is the thing this exemption exists to
 * prevent. It is not a <details open> either — that offers a control whose only function is to
 * hide the error, which is not a choice this surface should present.
 */
function AlertSection({ id, title, hint, children }) {
  return (
    <section className="panel" id={id} data-testid="rundetails-alert"
             style={{ borderLeft: '4px solid var(--danger,#b3261e)', marginBottom: 10 }}>
      <h3 style={{ margin: '0 0 6px', fontSize: 14, fontWeight: 650, display: 'flex',
                   alignItems: 'center', gap: 7 }}>
        {/* aria-hidden: the badge beside it is the accessible carrier, so a screen reader is not
            read a warning glyph it cannot name. */}
        <span aria-hidden="true">⚠</span>
        {title}
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '.02em', textTransform: 'uppercase',
                       color: 'var(--danger,#b3261e)', border: '1px solid var(--danger,#b3261e)',
                       borderRadius: 6, padding: '1px 6px' }}>Needs attention</span>
      </h3>
      {hint && <p className="muted" style={{ margin: '0 0 8px', fontSize: 12.5, lineHeight: 1.6 }}>{hint}</p>}
      <div>{children}</div>
    </section>
  )
}

/**
 * One disclosed section. `defaultOpen` is passed through to the native `open` attribute, so a
 * caller can bring a panel up already expanded when it has work in it — derived from content,
 * never a constant, for the reason RemSection's header sets out.
 */
function DisclosedSection({ id, title, hint, defaultOpen, children }) {
  return (
    <details className="panel rem-sec" id={id} open={!!defaultOpen} data-testid="rundetails-section">
      <summary className="rem-sec-sum">
        <h3 className="rem-sec-title" style={{ fontSize: 14, fontWeight: 650, margin: 0 }}>{title}</h3>
        {hint && <span className="muted rem-sec-hint" style={{ fontSize: 12.5 }}>{hint}</span>}
      </summary>
      <div className="rem-sec-body">{children}</div>
    </details>
  )
}

/**
 * @param sections  [{ id, title, hint, children, defaultOpen, alert }] — `id` is both the DOM id
 *                  and the React key; `alert` exempts the section from the disclosure entirely.
 * @param open      whether the disclosed surface is expanded. Seeds the internal state when
 *                  uncontrolled; drives the render when `onToggle` is supplied.
 * @param onToggle  (next:boolean) => void. Supplying it makes the component CONTROLLED: it stops
 *                  owning the state and reports the intent instead, so a host that wants the
 *                  surface open across a remount, or in a URL, can hold it. Null (the default)
 *                  leaves the component owning its own state, which is what a caller that does not
 *                  care about the state should get without wiring anything.
 * @param title     the toggle's label, and the surface's accessible name. Copy, not identity —
 *                  it stays 'Run details' regardless of what this module is called.
 */
export default function RemediationRunDetails({
  sections = [],
  open = false,
  onToggle = null,
  title = 'Run details',
}) {
  // Hooks before any early return — the empty case below must not change the hook order.
  const [selfOpen, setSelfOpen] = useState(open)
  const reactId = useId()

  const controlled = typeof onToggle === 'function'
  const isOpen = controlled ? !!open : selfOpen
  // useId() returns a colon-wrapped token (`:r0:`). It is a legal HTML id but not a legal CSS
  // selector unescaped, so anything that later wants to reach this panel — a test, a skip link, a
  // deep link from an email — has to know to escape it. Stripping to word characters keeps the
  // per-instance uniqueness that matters (r0, r1, …) and leaves an id you can just use.
  const panelId = `rundetails-panel-${reactId.replace(/[^a-zA-Z0-9_-]/g, '')}`

  // Sections with no body never reach the DOM — not as a <details>, not as a heading, and not as
  // part of the alert count. See hasBody.
  const live = sections.filter((s) => s && hasBody(s.children))
  const alerts = live.filter((s) => s.alert)
  const disclosed = live.filter((s) => !s.alert)

  // Nothing to disclose and nothing to warn about: render nothing at all rather than a control
  // that opens onto emptiness. Same contract as GroupedFixes and RunDetails — a surface with no
  // content is not a surface with empty content.
  if (live.length === 0) return null

  const toggle = () => {
    if (controlled) onToggle(!isOpen)
    else setSelfOpen((v) => !v)
  }

  // The count is part of the button's ACCESSIBLE NAME, not an adornment beside it: it has to
  // survive being read out of context by a screen reader, and it has to be legible without
  // colour. Pluralised because the string is user-facing copy — "2 needs attention" is the kind
  // of detail that reads as a machine talking.
  const attention = alerts.length === 0 ? ''
    : alerts.length === 1 ? ' (1 needs attention)'
    : ` (${alerts.length} need attention)`

  return (
    <section aria-label={title} className="rundetails-shell" data-testid="rundetails"
             style={{ marginTop: 14 }}>
      {/* Above the toggle, outside the disclosure, in every state. */}
      {alerts.map((s) => (
        <AlertSection key={s.id} id={s.id} title={s.title} hint={s.hint}>{s.children}</AlertSection>
      ))}

      <button type="button" className="ghost small" onClick={toggle}
              aria-expanded={isOpen} aria-controls={panelId} data-testid="rundetails-toggle"
              title="Reference and operational panels for this run — not needed to review a finding">
        <span aria-hidden="true" style={{ display: 'inline-block', marginRight: 6,
                                          transform: isOpen ? 'rotate(90deg)' : 'none' }}>▸</span>
        {title}{attention}
      </button>

      {/* The panel is REMOVED when collapsed rather than hidden, so its contents are out of the
          accessibility tree and out of the tab order without a second mechanism to keep in sync.
          The element itself stays mounted either way so aria-controls always resolves to a real
          node — an aria-controls pointing at nothing is a dangling reference, not a closed panel. */}
      <div id={panelId} data-testid="rundetails-panel"
           style={{ display: 'grid', gap: 10, marginTop: isOpen ? 10 : 0 }}>
        {isOpen && disclosed.map((s) => (
          <DisclosedSection key={s.id} id={s.id} title={s.title} hint={s.hint}
                            defaultOpen={s.defaultOpen}>{s.children}</DisclosedSection>
        ))}
      </div>
    </section>
  )
}

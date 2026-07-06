// 2.1.1 Keyboard (Level A)
// All functionality is operable through a keyboard interface.
// Fix: deterministic — non-interactive elements with onclick get tabindex=0,
//   role=button, AND an onkeydown forwarder (Enter/Space → click). Focusability
//   without activation is not keyboard support: a div you can Tab to but not
//   press still fails 2.1.1. Check and fix share one operability predicate so
//   a fixed document always re-checks clean.

export const meta = {
  id: '2.1.1',
  level: 'A',
  name: 'Keyboard',
  fixMode: 'auto', // tabindex + role + key forwarder is deterministic
}

const NATIVE_INTERACTIVE = /^(a|button|input|select|textarea|summary)$/i

// Inline-attribute equivalent of what a native <button> does for Enter/Space.
const KEY_FORWARDER =
  "if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}"

const isKeyboardOperable = (el) =>
  el.hasAttribute('onkeydown') &&
  el.hasAttribute('tabindex') &&
  el.getAttribute('tabindex') !== '-1'

export function check(doc) {
  const findings = []
  doc.querySelectorAll('[onclick]').forEach((el) => {
    if (NATIVE_INTERACTIVE.test(el.tagName)) return
    if (isKeyboardOperable(el)) return
    findings.push({
      element: el.outerHTML.slice(0, 120),
      detail: 'Click-only element is not keyboard-operable',
      severity: 'CRITICAL',
    })
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('[onclick]').forEach((el) => {
    if (NATIVE_INTERACTIVE.test(el.tagName)) return
    if (isKeyboardOperable(el)) return
    if (!el.hasAttribute('tabindex') || el.getAttribute('tabindex') === '-1')
      el.setAttribute('tabindex', '0')
    if (!el.getAttribute('role')) el.setAttribute('role', 'button')
    if (!el.hasAttribute('onkeydown')) el.setAttribute('onkeydown', KEY_FORWARDER)
    changes.add('Made click-only controls keyboard-operable · 2.1.1')
  })
  return changes
}

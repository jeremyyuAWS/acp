// 2.1.1 Keyboard (Level A)
// All functionality is operable through a keyboard interface.
// Fix: deterministic — non-interactive elements with onclick must be made focusable
//   (tabindex=0) and announced as buttons (role=button) so keyboard users can activate them.

export const meta = {
  id: '2.1.1',
  level: 'A',
  name: 'Keyboard',
  fixMode: 'auto', // tabindex + role addition is deterministic
}

const NATIVE_INTERACTIVE = /^(a|button|input|select|textarea|summary)$/i

export function check(doc) {
  const findings = []
  doc.querySelectorAll('[onclick]').forEach((el) => {
    if (!NATIVE_INTERACTIVE.test(el.tagName)) {
      findings.push({
        element: el.outerHTML.slice(0, 120),
        detail: 'Click-only element is not keyboard-operable',
        severity: 'CRITICAL',
      })
    }
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('[onclick]').forEach((el) => {
    if (NATIVE_INTERACTIVE.test(el.tagName)) return
    if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0')
    if (!el.getAttribute('role')) el.setAttribute('role', 'button')
    changes.add('Made click-only controls keyboard-operable · 2.1.1')
  })
  return changes
}

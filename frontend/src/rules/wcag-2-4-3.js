// 2.4.3 Focus Order (Level A)
// Focusable components receive focus in an order that preserves meaning and operability.
// Fix: deterministic — positive tabindex values override reading order and must be reset
//   to 0 (participates in natural DOM order) so keyboard users navigate logically.

export const meta = {
  id: '2.4.3',
  level: 'A',
  name: 'Focus Order',
  fixMode: 'auto', // resetting tabindex to 0 is always correct for positive values
}

export function check(doc) {
  const findings = []
  doc.querySelectorAll('[tabindex]').forEach((el) => {
    if (parseInt(el.getAttribute('tabindex'), 10) > 0) {
      findings.push({
        element: el.outerHTML.slice(0, 120),
        detail: `tabindex="${el.getAttribute('tabindex')}" overrides natural focus order`,
        severity: 'SERIOUS',
      })
    }
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('[tabindex]').forEach((el) => {
    if (parseInt(el.getAttribute('tabindex'), 10) > 0) {
      el.setAttribute('tabindex', '0')
      changes.add('Reset positive tabindex to keep focus order · 2.4.3')
    }
  })
  return changes
}

// 1.3.1 Info and Relationships (Level A)
// Information conveyed through presentation (labels, structure) is also available
// programmatically. Covers unlabeled form controls — the most common document failure.
// Fix: derives an aria-label from placeholder/name when no real label exists.
//   fixMode is 'ai-assisted' on purpose: a placeholder is often an example value
//   ("john@example.com") and a name attr a field code ("fld_23"), so derived
//   labels route to human review instead of silently certifying as fixed.

export const meta = {
  id: '1.3.1',
  level: 'A',
  name: 'Info and Relationships',
  fixMode: 'ai-assisted', // derived labels are guesses — verify before publish
}

// Controls that already have an accessible name without a <label>:
// hidden inputs aren't exposed to AT at all; buttons name themselves from value/alt.
const SELF_NAMED = /^(hidden|button|submit|reset|image)$/i

const hasLabel = (doc, inp) => {
  if (inp.getAttribute('aria-label') || inp.getAttribute('aria-labelledby')) return true
  if (inp.closest('label')) return true // implicit <label>wrapping</label>
  const id = inp.getAttribute('id')
  return Boolean(id && doc.querySelector(`label[for="${id}"]`))
}

const needsLabel = (doc, inp) =>
  !SELF_NAMED.test(inp.getAttribute('type') || '') && !hasLabel(doc, inp)

export function check(doc) {
  const findings = []
  doc.querySelectorAll('input, select, textarea').forEach((inp) => {
    if (!needsLabel(doc, inp)) return
    findings.push({
      element: inp.outerHTML.slice(0, 120),
      detail: 'Form control has no accessible label',
      severity: 'CRITICAL',
    })
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('input, select, textarea').forEach((inp) => {
    if (!needsLabel(doc, inp)) return
    // name attrs are usually field codes — humanize ("billing_zip" → "billing zip")
    const hint =
      inp.getAttribute('placeholder') ||
      (inp.getAttribute('name') || '').replace(/[_-]+/g, ' ').trim() ||
      'form field'
    inp.setAttribute('aria-label', hint)
    changes.add('Labeled form fields (derived — verify) · 1.3.1')
  })
  return changes
}

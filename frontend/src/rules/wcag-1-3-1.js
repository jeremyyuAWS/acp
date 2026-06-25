// 1.3.1 Info and Relationships (Level A)
// Information conveyed through presentation (labels, structure) is also available
// programmatically. Covers unlabeled form controls — the most common document failure.

export const meta = {
  id: '1.3.1',
  level: 'A',
  name: 'Info and Relationships',
  fixMode: 'auto', // placeholder label from placeholder/name attr is deterministic
}

export function check(doc) {
  const findings = []
  doc.querySelectorAll('input, select, textarea').forEach((inp) => {
    const id = inp.getAttribute('id')
    const labelled =
      inp.getAttribute('aria-label') ||
      inp.getAttribute('aria-labelledby') ||
      (id && doc.querySelector(`label[for="${id}"]`))
    if (!labelled) {
      findings.push({
        element: inp.outerHTML.slice(0, 120),
        detail: 'Form control has no accessible label',
        severity: 'CRITICAL',
      })
    }
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('input, select, textarea').forEach((inp) => {
    const id = inp.getAttribute('id')
    const labelled =
      inp.getAttribute('aria-label') ||
      inp.getAttribute('aria-labelledby') ||
      (id && doc.querySelector(`label[for="${id}"]`))
    if (!labelled) {
      const hint =
        inp.getAttribute('placeholder') ||
        inp.getAttribute('name') ||
        'form field'
      inp.setAttribute('aria-label', hint)
      changes.add('Labeled form fields · 1.3.1')
    }
  })
  return changes
}

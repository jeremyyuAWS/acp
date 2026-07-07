// 3.3.2 Labels or Instructions (Level A)
// User input is preceded by a label or instructions. Focuses on REQUIRED fields
// with no guidance at all — the case where a user cannot know what to enter.
// Fix mirrors 1.3.1's posture: a derived label is a guess, so fixMode is
//   'ai-assisted' and every derived instruction routes to human review.

export const meta = {
  id: '3.3.2',
  level: 'A',
  name: 'Labels or Instructions',
  fixMode: 'ai-assisted', // derived instructions are guesses — verify in HITL
}

const hasGuidance = (doc, inp) => {
  if (inp.getAttribute('aria-label') || inp.getAttribute('aria-labelledby')
    || inp.getAttribute('aria-describedby') || inp.getAttribute('title')
    || inp.getAttribute('placeholder')) return true
  if (inp.closest('label')) return true
  const id = inp.getAttribute('id')
  return Boolean(id && doc.querySelector(`label[for="${id}"]`))
}

const needsGuidance = (doc, inp) =>
  inp.hasAttribute('required') && !hasGuidance(doc, inp)

export function check(doc) {
  const findings = []
  doc.querySelectorAll('input, select, textarea').forEach((inp) => {
    if (!needsGuidance(doc, inp)) return
    findings.push({
      element: inp.outerHTML.slice(0, 120),
      detail: 'Required field gives the user no label or instructions',
      severity: 'SERIOUS',
    })
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('input, select, textarea').forEach((inp) => {
    if (!needsGuidance(doc, inp)) return
    const hint = (inp.getAttribute('name') || 'this field').replace(/[_-]+/g, ' ').trim()
    inp.setAttribute('aria-label', `${hint} (required)`)
    changes.add('Added instructions to required fields (derived — verify) · 3.3.2')
  })
  return changes
}

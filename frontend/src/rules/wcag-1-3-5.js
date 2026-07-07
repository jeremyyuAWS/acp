// 1.3.5 Identify Input Purpose (Level AA)
// Inputs collecting personal data declare their purpose programmatically
// (autocomplete tokens), so browsers/AT can assist filling them.
// Fix: deterministic — the token is derived from the input's type/name against
//   the WCAG 2.1 §7 input-purposes list; unrecognizable fields are left alone.

export const meta = {
  id: '1.3.5',
  level: 'AA',
  name: 'Identify Input Purpose',
  fixMode: 'auto', // token mapping is a fixed lookup; no guessing beyond it
}

// name/id patterns → autocomplete token (subset of the WCAG input-purposes list
// that can be recognized deterministically; anything else is not flagged).
// Boundaries include \s: the hint is "name id placeholder" joined by spaces, so a
// keyword at the end of any one attribute is followed by a space, not $.
const PURPOSES = [
  [/e-?mail/i, 'email'],
  [/(^|[\s_-])(tel|phone|mobile)([\s_-]|$)/i, 'tel'],
  [/(first|given)[-_ ]?name/i, 'given-name'],
  [/(last|family|sur)[-_ ]?name/i, 'family-name'],
  [/full[-_ ]?name|^name$/i, 'name'],
  [/(^|[\s_-])(zip|postal)([-_ ]?code)?([\s_-]|$)/i, 'postal-code'],
  [/(^|[\s_-])country([\s_-]|$)/i, 'country-name'],
  [/(^|[\s_-])(city|town)([\s_-]|$)/i, 'address-level2'],
  [/street|address[-_ ]?(line)?[-_ ]?1?\b/i, 'street-address'],
  [/(^|[\s_-])(org|organization|company)([\s_-]|$)/i, 'organization'],
  [/birth[-_ ]?(date|day)|(^|[\s_-])dob([\s_-]|$)/i, 'bday'],
]

const purposeOf = (inp) => {
  const type = (inp.getAttribute('type') || '').toLowerCase()
  if (type === 'email') return 'email'
  if (type === 'tel') return 'tel'
  const hint = `${inp.getAttribute('name') || ''} ${inp.getAttribute('id') || ''} ${inp.getAttribute('placeholder') || ''}`
  for (const [re, token] of PURPOSES) if (re.test(hint)) return token
  return null
}

const needsToken = (inp) => !inp.getAttribute('autocomplete') && purposeOf(inp) !== null

export function check(doc) {
  const findings = []
  doc.querySelectorAll('input').forEach((inp) => {
    if (!needsToken(inp)) return
    findings.push({
      element: inp.outerHTML.slice(0, 120),
      detail: `Personal-data field has no autocomplete purpose (should be "${purposeOf(inp)}")`,
      severity: 'MODERATE',
    })
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('input').forEach((inp) => {
    if (!needsToken(inp)) return
    inp.setAttribute('autocomplete', purposeOf(inp))
    changes.add('Declared input purposes with autocomplete tokens · 1.3.5')
  })
  return changes
}

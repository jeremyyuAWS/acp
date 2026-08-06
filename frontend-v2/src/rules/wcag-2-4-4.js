// 2.4.4 Link Purpose (In Context) (Level A)
// The purpose of each link can be determined from the link text alone or with context.
// Fix: ai-assisted — adding a meaningful aria-label requires understanding what the link
//   targets; we add a structural fallback using the page title, but AI does it better.

import { AMBIGUOUS_LINK } from './utils.js'

export const meta = {
  id: '2.4.4',
  level: 'A',
  name: 'Link Purpose (In Context)',
  fixMode: 'ai-assisted', // AI rewrites the label with context from the surrounding content
}

export function check(doc) {
  const findings = []
  doc.querySelectorAll('a').forEach((a) => {
    if (AMBIGUOUS_LINK.test((a.textContent || '').trim()) && !a.getAttribute('aria-label')) {
      findings.push({
        element: a.outerHTML.slice(0, 120),
        detail: `Ambiguous link text "${(a.textContent || '').trim()}"`,
        severity: 'SERIOUS',
      })
    }
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('a').forEach((a) => {
    if (AMBIGUOUS_LINK.test((a.textContent || '').trim())) {
      a.setAttribute(
        'aria-label',
        `${a.textContent.trim()} — ${doc.title || 'link'}`
      )
      changes.add('Clarified ambiguous links · 2.4.4')
    }
  })
  return changes
}

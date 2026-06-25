// 1.4.11 Non-text Contrast (Level AA)
// UI components and graphical objects have a contrast ratio of at least 3:1 against
// adjacent colors. Covers declared inline border colors on interactive controls.

import { isLight } from './utils.js'

export const meta = {
  id: '1.4.11',
  level: 'AA',
  name: 'Non-text Contrast',
  fixMode: 'ai-assisted', // designer should choose the right compliant colour; #767676 is the safe fallback
}

export function check(doc) {
  const findings = []
  doc.querySelectorAll('[style*="border"]').forEach((el) => {
    const s = el.getAttribute('style')
    const m = /border(?:-[a-z]+)?:[^;]*?(#[0-9a-fA-F]{3,6})/.exec(s)
    if (m && isLight(m[1])) {
      findings.push({
        element: el.outerHTML.slice(0, 120),
        detail: `Border color ${m[1]} is likely below 3:1 non-text contrast`,
        severity: 'MODERATE',
      })
    }
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('[style*="border"]').forEach((el) => {
    const s = el.getAttribute('style')
    const m = /border(?:-[a-z]+)?:[^;]*?(#[0-9a-fA-F]{3,6})/.exec(s)
    if (m && isLight(m[1])) {
      el.setAttribute('style', s.replace(m[1], '#767676'))
      changes.add('Darkened low-contrast UI borders to 3:1 · 1.4.11')
    }
  })
  return changes
}

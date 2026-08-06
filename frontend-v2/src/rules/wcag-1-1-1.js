// 1.1.1 Non-text Content (Level A)
// All non-text content has a text alternative.
// Check: deterministic (missing alt attribute is always a finding).
// Fix: ai-assisted — a Vision model generates meaningful alt text; filename is used as
//   a deterministic fallback so the attribute is never empty even without AI.

import { altFromSrc } from './utils.js'

export const meta = {
  id: '1.1.1',
  level: 'A',
  name: 'Non-text Content',
  fixMode: 'ai-assisted', // AI (Vision) produces semantically correct alt text
}

export function check(doc) {
  const findings = []
  doc.querySelectorAll('img').forEach((img) => {
    if (img.getAttribute('alt') === null) {
      findings.push({
        element: img.outerHTML.slice(0, 120),
        detail: 'Image missing alt attribute',
        severity: 'CRITICAL',
      })
    }
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('img').forEach((img) => {
    if (img.getAttribute('alt') === null) {
      img.setAttribute('alt', altFromSrc(img.getAttribute('src')))
      changes.add('Generated alt text for images · 1.1.1')
    }
  })
  return changes
}

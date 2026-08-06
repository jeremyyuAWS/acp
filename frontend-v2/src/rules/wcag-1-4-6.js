// 1.4.6 Contrast (Enhanced) (Level AAA)
// Text contrast of at least 7:1 (4.5:1 for large text). The enhanced sibling of
// 1.4.3 — same inline-style heuristic, stricter threshold. The 1.4.3 fix already
// darkens to #333333 (9.7:1 on white), which satisfies this ratio too, so both
// modules converge on the same recolour.

import { isLight } from './utils.js'

export const meta = {
  id: '1.4.6',
  level: 'AAA',
  name: 'Contrast (Enhanced)',
  fixMode: 'auto', // same deterministic recolour as 1.4.3
}

// Mid-greys (e.g. #767676) pass 4.5:1 but fail 7:1 — flag anything lighter than
// ~0.45 relative luma, a stricter cut than utils.isLight()'s 0.62 for 1.4.3.
const failsEnhanced = (hex) => {
  let h = hex.replace('#', '')
  if (h.length === 3) h = h.split('').map((c) => c + c).join('')
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16)
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.45
}

export function check(doc) {
  const findings = []
  doc.querySelectorAll('[style*="color"]').forEach((el) => {
    const s = el.getAttribute('style')
    const m = /(^|[^-])color:\s*(#[0-9a-fA-F]{3,6})/.exec(s)
    if (m && failsEnhanced(m[2])) {
      findings.push({
        element: el.outerHTML.slice(0, 120),
        detail: `Inline color ${m[2]} is likely below the enhanced 7:1 ratio`,
        severity: 'MODERATE',
      })
    }
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('[style*="color"]').forEach((el) => {
    const s = el.getAttribute('style')
    const m = /(^|[^-])color:\s*(#[0-9a-fA-F]{3,6})/.exec(s)
    if (m && failsEnhanced(m[2])) {
      el.setAttribute('style', s.replace(m[2], '#333333'))
      changes.add('Darkened text to meet the enhanced 7:1 contrast · 1.4.6')
    }
  })
  return changes
}

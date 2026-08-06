// 1.4.1 Use of Color (Level A)
// Color is not the only visual means of conveying information.
// Fix: deterministic — links whose inline style sets a color but no underline
//   get an explicit text-decoration:underline so they are distinguishable
//   without color perception. Check and fix share one predicate so a fixed
//   document always re-checks clean. Inline styles only (same limitation as
//   the contrast rules): class/stylesheet colors aren't visible to DOM checks.

export const meta = {
  id: '1.4.1',
  level: 'A',
  name: 'Use of Color',
  fixMode: 'auto', // adding text-decoration:underline is always safe
}

// (?:^|;) anchors the property name so background-color/border-color don't match.
const reliesOnColorAlone = (a) => {
  const s = a.getAttribute('style') || ''
  return /(?:^|;)\s*color\s*:/i.test(s) && !/text-decoration\s*:[^;]*underline/i.test(s)
}

export function check(doc) {
  const findings = []
  doc.querySelectorAll('a[style]').forEach((a) => {
    if (!reliesOnColorAlone(a)) return
    findings.push({
      element: a.outerHTML.slice(0, 120),
      detail: 'Link is distinguished by colour alone (no underline)',
      severity: 'SERIOUS',
    })
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('a[style]').forEach((a) => {
    if (!reliesOnColorAlone(a)) return
    const s = a.getAttribute('style')
    // Replace an explicit text-decoration (e.g. none) rather than stacking a
    // conflicting second declaration.
    const next = /text-decoration\s*:/i.test(s)
      ? s.replace(/text-decoration\s*:[^;]*/i, 'text-decoration:underline')
      : s.replace(/;?\s*$/, '; ') + 'text-decoration:underline'
    a.setAttribute('style', next)
    changes.add('Underlined links styled by colour alone · 1.4.1')
  })
  return changes
}

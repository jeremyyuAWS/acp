// 1.4.1 Use of Color (Level A)
// Color is not the only visual means of conveying information.
// Fix: deterministic — in-text links that rely on color alone (no text-decoration)
//   get an explicit underline so they are distinguishable without color perception.

export const meta = {
  id: '1.4.1',
  level: 'A',
  name: 'Use of Color',
  fixMode: 'auto', // adding text-decoration:underline is always safe
}

export function check(doc) {
  const findings = []
  doc.querySelectorAll('p a, li a, td a').forEach((a) => {
    const s = a.getAttribute('style') || ''
    if (/color\s*:/i.test(s) && !/text-decoration\s*:\s*underline/i.test(s)) {
      findings.push({
        element: a.outerHTML.slice(0, 120),
        detail: 'In-text link is distinguished by colour alone (no underline)',
        severity: 'SERIOUS',
      })
    }
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('p a, li a, td a').forEach((a) => {
    const s = a.getAttribute('style') || ''
    if (/text-decoration[^;]*none/i.test(s) || !/text-decoration/i.test(s)) {
      a.setAttribute(
        'style',
        (s ? s.replace(/;?\s*$/, '; ') : '') + 'text-decoration:underline'
      )
      changes.add('Underlined in-text links (not colour alone) · 1.4.1')
    }
  })
  return changes
}

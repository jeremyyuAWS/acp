// 2.4.6 Headings and Labels (Level AA)
// Headings and labels describe topic or purpose.
// Fix: promote visually-styled pseudo-headings (large+bold short leaf text) to real
//   <h2> elements so screen-reader users can navigate the document by heading.
//   Detection heuristic: font-size >= 18px AND font-weight: bold/600+, text < 50 chars.

export const meta = {
  id: '2.4.6',
  level: 'AA',
  name: 'Headings and Labels',
  fixMode: 'auto', // structural promotion is deterministic from inline style signals
}

export function check(doc) {
  const findings = []
  doc.querySelectorAll('p, div').forEach((el) => {
    if (el.children.length) return
    const txt = (el.textContent || '').trim()
    if (!txt || txt.length > 50 || /[.?!]$/.test(txt)) return
    const s = el.getAttribute('style') || ''
    const fs = parseInt((/font-size:\s*(\d+)px/i.exec(s) || [])[1] || 0, 10)
    if (fs >= 18 && /font-weight:\s*(bold|[6-9]00)/i.test(s)) {
      findings.push({
        element: el.outerHTML.slice(0, 120),
        detail: 'Visually-styled text looks like a heading but is not a real heading element',
        severity: 'MODERATE',
      })
    }
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('p, div').forEach((el) => {
    if (el.children.length) return
    const txt = (el.textContent || '').trim()
    if (!txt || txt.length > 50 || /[.?!]$/.test(txt)) return
    const s = el.getAttribute('style') || ''
    const fs = parseInt((/font-size:\s*(\d+)px/i.exec(s) || [])[1] || 0, 10)
    if (fs >= 18 && /font-weight:\s*(bold|[6-9]00)/i.test(s)) {
      const h = doc.createElement('h2')
      h.textContent = txt
      if (s) h.setAttribute('style', s)
      el.replaceWith(h)
      changes.add('Promoted styled text to real headings · 2.4.6')
    }
  })
  return changes
}

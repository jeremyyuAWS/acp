// 1.4.12 Text Spacing (Level AA)
// No loss of content or functionality occurs when the user overrides letter/word/line
// spacing. Fix: replace fixed-px line-heights with a unitless ratio so the browser's
// text-spacing override doesn't cause clipping.

export const meta = {
  id: '1.4.12',
  level: 'AA',
  name: 'Text Spacing',
  fixMode: 'auto', // unitless ratio is always safe regardless of font-size
}

export function check(doc) {
  const findings = []
  doc.querySelectorAll('[style*="line-height"]').forEach((el) => {
    if (/line-height:\s*\d+px/i.test(el.getAttribute('style') || '')) {
      findings.push({
        element: el.outerHTML.slice(0, 120),
        detail: 'Fixed-pixel line-height blocks user text-spacing overrides',
        severity: 'MODERATE',
      })
    }
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('[style*="line-height"]').forEach((el) => {
    const s = el.getAttribute('style')
    if (/line-height:\s*\d+px/i.test(s)) {
      el.setAttribute('style', s.replace(/line-height:\s*\d+px/i, 'line-height:1.5'))
      changes.add('Unblocked text-spacing overrides · 1.4.12')
    }
  })
  return changes
}

// 2.5.8 Target Size (Minimum) (Level AA, added in WCAG 2.2)
// Pointer targets are at least 24×24 CSS px (spacing/inline exceptions aside).
// Detect-and-route: interactive elements whose INLINE style sets a width or
// height below 24px are flagged. Inline-only, like the contrast rules — a target
// sized by a class/stylesheet isn't visible to a DOM check. The fix (enlarging)
// is layout-sensitive, so a reviewer decides the right size → fixMode 'human-only'.

export const meta = {
  id: '2.5.8',
  level: 'AA',
  name: 'Target Size (Minimum)',
  fixMode: 'human-only', // resizing can overflow layout — human picks the size
}

const INTERACTIVE = 'a[href], button, input, select, textarea, [role="button"], [onclick]'
const MIN = 24

// Pull an inline px dimension; returns null when absent or non-px (%/em/auto).
const pxDim = (style, prop) => {
  const m = new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*([\\d.]+)px`, 'i').exec(style || '')
  return m ? parseFloat(m[1]) : null
}

const tooSmall = (el) => {
  const s = el.getAttribute('style') || ''
  const w = pxDim(s, 'width')
  const h = pxDim(s, 'height')
  return (w !== null && w < MIN) || (h !== null && h < MIN)
}

export function check(doc) {
  const findings = []
  doc.querySelectorAll(INTERACTIVE).forEach((el) => {
    if (!tooSmall(el)) return
    findings.push({
      element: el.outerHTML.slice(0, 120),
      detail: 'Interactive target is smaller than 24×24px — hard to hit for motor-impaired users',
      severity: 'SERIOUS',
    })
  })
  return findings
}

export function fix() {
  return new Set()
}

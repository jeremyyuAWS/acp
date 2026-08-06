// 1.3.4 Orientation (Level AA, added in WCAG 2.1) — content is not locked to a
// single display orientation. The lock pattern in documents: a CSS @media block
// for one orientation that hides content (the "please rotate your device" overlay).
// Fix: deterministic — neutralize display:none inside orientation media queries.

export const meta = {
  id: '1.3.4',
  level: 'AA',
  name: 'Orientation',
  fixMode: 'auto', // un-hiding orientation-locked content is safe
}

const LOCK = /@media[^{]*\(\s*orientation\s*:\s*(?:portrait|landscape)\s*\)[^{]*\{[^@]*?display\s*:\s*none/i

export function check(doc) {
  const findings = []
  doc.querySelectorAll('style').forEach((st) => {
    if (!LOCK.test(st.textContent || '')) return
    findings.push({
      element: (st.textContent || '').trim().slice(0, 120),
      detail: 'Content is hidden in one screen orientation (orientation lock)',
      severity: 'MODERATE',
    })
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('style').forEach((st) => {
    const css = st.textContent || ''
    if (!LOCK.test(css)) return
    // Neutralize only display:none declarations inside orientation blocks —
    // scoped enough for document exports, which never have nested @media.
    st.textContent = css.replace(
      /(@media[^{]*\(\s*orientation\s*:\s*(?:portrait|landscape)\s*\)[^{]*\{[^@]*?)display\s*:\s*none\s*;?/gi,
      '$1'
    )
    changes.add('Removed the single-orientation content lock · 1.3.4')
  })
  return changes
}

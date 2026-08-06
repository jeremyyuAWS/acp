// 2.4.7 Focus Visible (Level AA)
// Any keyboard-operable UI has a visible focus indicator.
// Fix: deterministic — when the page suppresses focus outlines (outline:none/0 in
//   stylesheets or inline), inject a :focus-visible rule so keyboard users always see
//   where they are. Only applied when there are interactive elements to focus.

export const meta = {
  id: '2.4.7',
  level: 'AA',
  name: 'Focus Visible',
  fixMode: 'auto', // injecting a CSS rule is deterministic
}

export function check(doc) {
  const css = [...doc.querySelectorAll('style')].map((s) => s.textContent || '').join('\n')
  const suppressed =
    /outline:\s*(none|0)\b/i.test(css) ||
    [...doc.querySelectorAll('[style*="outline"]')].some((el) =>
      /outline:\s*(none|0)\b/i.test(el.getAttribute('style') || '')
    )
  if (suppressed && doc.querySelector('a, button, input, select, textarea')) {
    return [{ element: '<style>', detail: 'Focus outline is suppressed — keyboard users cannot see focus', severity: 'SERIOUS' }]
  }
  return []
}

export function fix(doc) {
  const changes = new Set()
  const css = [...doc.querySelectorAll('style')].map((s) => s.textContent || '').join('\n')
  const suppressed =
    /outline:\s*(none|0)\b/i.test(css) ||
    [...doc.querySelectorAll('[style*="outline"]')].some((el) =>
      /outline:\s*(none|0)\b/i.test(el.getAttribute('style') || '')
    )
  if (suppressed && doc.querySelector('a, button, input, select, textarea')) {
    const st = doc.createElement('style')
    st.textContent = ':focus-visible{outline:2px solid #1F5FA8;outline-offset:2px}'
    ;(doc.head || doc.documentElement).appendChild(st)
    changes.add('Ensured a visible keyboard focus indicator · 2.4.7')
  }
  return changes
}

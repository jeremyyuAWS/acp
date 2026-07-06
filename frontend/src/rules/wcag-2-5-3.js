// 2.5.3 Label in Name (Level A)
// The accessible name of a control contains its visible label text, so
// voice-control users can activate it by saying what they see.
// Fix: deterministic — an aria-label that omits the visible text is rebuilt to
//   start with the visible text (any extra context from the old label is kept).

export const meta = {
  id: '2.5.3',
  level: 'A',
  name: 'Label in Name',
  fixMode: 'auto', // visible text is authoritative; prepending it is safe
}

const norm = (s) => (s || '').toLowerCase().replace(/\s+/g, ' ').trim()

const mismatch = (el) => {
  const aria = norm(el.getAttribute('aria-label'))
  if (!aria) return false
  const visible = norm(el.textContent).slice(0, 80)
  return Boolean(visible) && !aria.includes(visible)
}

export function check(doc) {
  const findings = []
  doc.querySelectorAll('a[aria-label], button[aria-label], [role="button"][aria-label]').forEach((el) => {
    if (!mismatch(el)) return
    findings.push({
      element: el.outerHTML.slice(0, 120),
      detail: 'Accessible name does not contain the visible label text (breaks voice control)',
      severity: 'SERIOUS',
    })
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('a[aria-label], button[aria-label], [role="button"][aria-label]').forEach((el) => {
    if (!mismatch(el)) return
    const visible = (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80)
    const old = (el.getAttribute('aria-label') || '').trim()
    el.setAttribute('aria-label', old ? `${visible} — ${old}` : visible)
    changes.add('Aligned accessible names with visible labels · 2.5.3')
  })
  return changes
}

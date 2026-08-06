// 4.1.2 Name, Role, Value (Level A)
// All UI components have a name and role that can be programmatically determined.
// Fix: ai-assisted — icon-only controls need a meaningful accessible name; the
//   deterministic fallback uses an img alt or element type ("button"/"link") as a hint,
//   but AI produces a better description from surrounding context.

export const meta = {
  id: '4.1.2',
  level: 'A',
  name: 'Name, Role, Value',
  fixMode: 'ai-assisted', // AI can name icon controls by inferring from page context
}

export function check(doc) {
  const findings = []
  doc.querySelectorAll('button, [role="button"], a').forEach((el) => {
    if (
      !(el.textContent || '').trim() &&
      !el.getAttribute('aria-label') &&
      !el.getAttribute('title')
    ) {
      findings.push({
        element: el.outerHTML.slice(0, 120),
        detail: 'Control has no accessible name (icon-only)',
        severity: 'CRITICAL',
      })
    }
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('button, [role="button"], a').forEach((el) => {
    if ((el.textContent || '').trim() || el.getAttribute('aria-label') || el.getAttribute('title')) return
    const hint =
      el.querySelector('img[alt]')?.getAttribute('alt')?.trim() ||
      el.getAttribute('name') ||
      (el.tagName === 'A' ? 'link' : 'button')
    el.setAttribute('aria-label', hint)
    changes.add('Named unlabeled controls (icon-only) · 4.1.2')
  })
  return changes
}

// 3.1.1 Language of Page (Level A)
// The human language of the document must be programmatically determinable.
// Fix: add lang="en" to <html> when missing.

export const meta = {
  id: '3.1.1',
  level: 'A',
  name: 'Language of Page',
  fixMode: 'auto', // deterministic — only one correct attribute to add
}

export function check(doc) {
  if (!doc.documentElement.getAttribute('lang')) {
    return [{ element: '<html>', detail: 'Document language is not declared', severity: 'SERIOUS' }]
  }
  return []
}

export function fix(doc) {
  const changes = new Set()
  if (!doc.documentElement.getAttribute('lang')) {
    doc.documentElement.setAttribute('lang', 'en')
    changes.add('Set document language to English · 3.1.1')
  }
  return changes
}

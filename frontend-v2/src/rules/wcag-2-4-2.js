// 2.4.2 Page Titled (Level A)
// Web pages have titles that describe topic or purpose.
// Fix: generate a title from the first <h1> when <title> is absent or blank.

export const meta = {
  id: '2.4.2',
  level: 'A',
  name: 'Page Titled',
  fixMode: 'auto', // deterministic — use h1 text or "Document" as fallback
}

export function check(doc) {
  const t = doc.querySelector('title')
  if (!t || !t.textContent.trim()) {
    return [{ element: '<title>', detail: 'Document has no descriptive title', severity: 'SERIOUS' }]
  }
  return []
}

export function fix(doc) {
  const changes = new Set()
  let title = doc.querySelector('title')
  if (!title || !title.textContent.trim()) {
    if (!title) {
      title = doc.createElement('title')
      ;(doc.head || doc.documentElement).appendChild(title)
    }
    title.textContent = (doc.querySelector('h1')?.textContent?.trim() || 'Document').slice(0, 80)
    changes.add('Added a descriptive page title · 2.4.2')
  }
  return changes
}

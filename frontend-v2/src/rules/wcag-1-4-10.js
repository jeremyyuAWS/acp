// 1.4.10 Reflow (Level AA)
// Content reflows to a single column at 320 CSS pixels wide without horizontal scroll.
// Fix: deterministic — inject a responsive viewport meta when none exists, which enables
//   the browser's natural reflow behaviour.

export const meta = {
  id: '1.4.10',
  level: 'AA',
  name: 'Reflow',
  fixMode: 'auto', // adding the viewport tag is fully deterministic
}

export function check(doc) {
  const vp = doc.querySelector('meta[name="viewport"]')
  if (!vp && doc.querySelector('meta, link, style')) {
    return [{ element: '<head>', detail: 'No responsive viewport meta — content will not reflow at 320px', severity: 'SERIOUS' }]
  }
  return []
}

export function fix(doc) {
  const changes = new Set()
  if (!doc.querySelector('meta[name="viewport"]') && doc.querySelector('meta, link, style')) {
    const vp = doc.createElement('meta')
    vp.setAttribute('name', 'viewport')
    vp.setAttribute('content', 'width=device-width, initial-scale=1')
    ;(doc.head || doc.documentElement).insertBefore(vp, doc.head?.firstChild || null)
    changes.add('Added a responsive viewport for reflow · 1.4.10')
  }
  return changes
}

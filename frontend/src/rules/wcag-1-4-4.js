// 1.4.4 Resize Text (Level AA)
// Text resizes to 200% without loss of content or function.
// Fix: deterministic — remove user-scalable=no / maximum-scale=1 from the viewport meta.

export const meta = {
  id: '1.4.4',
  level: 'AA',
  name: 'Resize Text',
  fixMode: 'auto', // viewport string manipulation is fully deterministic
}

const BLOCKS_ZOOM = /user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*(0|1)(\.0+)?\b/i

export function check(doc) {
  const vp = doc.querySelector('meta[name="viewport"]')
  if (vp && BLOCKS_ZOOM.test(vp.getAttribute('content') || '')) {
    return [{ element: vp.outerHTML, detail: 'Viewport blocks user zoom/text resize', severity: 'SERIOUS' }]
  }
  return []
}

export function fix(doc) {
  const changes = new Set()
  const vp = doc.querySelector('meta[name="viewport"]')
  if (vp) {
    const c = vp.getAttribute('content') || ''
    if (BLOCKS_ZOOM.test(c)) {
      const fixed = c
        .replace(/,?\s*user-scalable\s*=\s*[^,]+/ig, '')
        .replace(/,?\s*maximum-scale\s*=\s*[^,]+/ig, '')
        .replace(/^\s*,|,\s*$/g, '')
        .trim()
      vp.setAttribute('content', fixed || 'width=device-width, initial-scale=1')
      changes.add('Re-enabled pinch-zoom & text resize · 1.4.4')
    }
  }
  return changes
}

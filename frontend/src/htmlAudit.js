// REAL WCAG detection for uploaded HTML, fully in the browser. The markup is
// rendered into a hidden, same-origin, script-disabled iframe and analysed with
// axe-core (the same engine many partner scanners use). axe-core is lazy-loaded.
const SC_NAME = {
  '1.1.1': 'non-text content', '1.3.1': 'info & relationships', '1.3.3': 'sensory characteristics',
  '1.3.5': 'identify input purpose', '1.4.1': 'use of color', '1.4.3': 'contrast', '1.4.4': 'resize text',
  '1.4.5': 'images of text', '1.4.10': 'reflow', '1.4.11': 'non-text contrast', '1.4.12': 'text spacing',
  '2.1.1': 'keyboard', '2.1.2': 'no keyboard trap', '2.4.1': 'bypass blocks', '2.4.2': 'page titled',
  '2.4.3': 'focus order', '2.4.4': 'link purpose', '2.5.3': 'label in name', '3.1.1': 'language of page',
  '3.1.2': 'language of parts', '3.3.2': 'labels or instructions', '4.1.1': 'parsing', '4.1.2': 'name, role, value',
}
const SEV = { critical: 'CRITICAL', serious: 'SERIOUS', moderate: 'MODERATE', minor: 'MINOR' }

const scOf = (tags) => { const m = (tags || []).map((t) => /^wcag(\d)(\d)(\d+)$/.exec(t)).find(Boolean); return m ? `${m[1]}.${m[2]}.${m[3]}` : '' }

// axe violations -> the Upload findings shape ({ rule, wcag, sev, detail }).
export function mapAxe(violations = []) {
  return violations.map((v) => {
    const sc = scOf(v.tags)
    const name = SC_NAME[sc]
    const n = v.nodes?.length || 1
    return {
      rule: v.id,
      wcag: sc ? `${sc}${name ? ` ${name}` : ''}` : v.id,
      sev: SEV[v.impact] || 'MODERATE',
      detail: `${n} element${n === 1 ? '' : 's'} — ${(v.help || v.description || '').replace(/\.$/, '')}`,
    }
  }).sort((a, b) => ['CRITICAL', 'SERIOUS', 'MODERATE', 'MINOR'].indexOf(a.sev) - ['CRITICAL', 'SERIOUS', 'MODERATE', 'MINOR'].indexOf(b.sev))
}

export async function auditHtml(html) {
  const mod = await import('axe-core'); const axe = mod.default || mod
  const doc = new DOMParser().parseFromString(html, 'text/html')
  // Render into a shadow root: the page's own <style> stays isolated (no bleed
  // into the app), and axe-core traverses open shadow DOM.
  const host = document.createElement('div')
  host.style.cssText = 'position:fixed;left:-10000px;top:0;width:1024px;height:768px;overflow:hidden'
  const shadow = host.attachShadow({ mode: 'open' })
  doc.head.querySelectorAll('style').forEach((s) => shadow.appendChild(document.importNode(s, true))) // eslint-disable-line
  ;[...doc.body.childNodes].forEach((n) => shadow.appendChild(document.importNode(n, true)))
  document.body.appendChild(host)
  try {
    const results = await axe.run(host, { resultTypes: ['violations'], runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } })
    const v = [...results.violations]
    // Document-level checks the fragment can't see — read straight from the parsed doc.
    if (!doc.documentElement.getAttribute('lang')) v.push({ id: 'html-has-lang', tags: ['wcag311'], impact: 'serious', help: 'document language is not set', nodes: [{}] })
    const title = doc.querySelector('title')
    if (!title || !title.textContent.trim()) v.push({ id: 'document-title', tags: ['wcag242'], impact: 'serious', help: 'document has no title', nodes: [{}] })
    // Extra structural checks, added only when axe hasn't already flagged that SC.
    const has = (sc) => v.some((x) => (x.tags || []).includes('wcag' + sc.replace(/\./g, '')))
    const add = (sc, tag, impact, help, n) => { if (n > 0 && !has(sc)) v.push({ id: 'mova-' + sc, tags: ['wcag' + sc.replace(/\./g, '')], impact, help, nodes: Array.from({ length: n }, () => ({})) }) }
    const vp = doc.querySelector('meta[name="viewport"]')
    if (vp && /user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*(0|1)(\.0+)?\b/i.test(vp.getAttribute('content') || '')) add('1.4.4', '', 'serious', 'viewport blocks zoom — text cannot be resized to 200%', 1)
    add('2.4.3', '', 'serious', 'positive tabindex overrides the natural focus order', [...doc.querySelectorAll('[tabindex]')].filter((e) => parseInt(e.getAttribute('tabindex'), 10) > 0).length)
    add('2.1.1', '', 'critical', 'click-only element is not keyboard-operable', [...doc.querySelectorAll('[onclick]')].filter((e) => !/^(a|button|input|select|textarea|summary)$/i.test(e.tagName)).length)
    add('1.4.1', '', 'serious', 'in-text link distinguished by colour alone', [...doc.querySelectorAll('p a, li a, td a')].filter((a) => { const s = a.getAttribute('style') || ''; return /color\s*:/i.test(s) && !/text-decoration\s*:\s*underline/i.test(s) }).length)
    return mapAxe(v)
  } finally { host.remove() }
}

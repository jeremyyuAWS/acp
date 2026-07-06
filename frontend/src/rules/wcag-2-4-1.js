// 2.4.1 Bypass Blocks (Level A)
// A mechanism exists to skip repeated blocks of content (skip link / landmark).
// Only meaningful when the document HAS repeated chrome — plain document exports
// with no nav/header are not flagged (documents open straight at their content).
// Fix: deterministic — add a main landmark around the content after the chrome,
//   plus a skip link targeting it.

export const meta = {
  id: '2.4.1',
  level: 'A',
  name: 'Bypass Blocks',
  fixMode: 'auto', // landmark + skip link injection is structural and safe
}

const hasChrome = (doc) => Boolean(doc.querySelector('nav, header, [role="navigation"], [role="banner"]'))
const hasBypass = (doc) => {
  if (doc.querySelector('main, [role="main"]')) return true
  // A skip link: an early same-page anchor whose target exists.
  const a = doc.querySelector('body a[href^="#"]')
  const target = a && a.getAttribute('href').slice(1)
  return Boolean(target && doc.getElementById(target))
}

export function check(doc) {
  if (!hasChrome(doc) || hasBypass(doc)) return []
  return [{
    element: (doc.body?.outerHTML || '').slice(0, 120),
    detail: 'Repeated navigation/header with no skip link or main landmark',
    severity: 'MODERATE',
  }]
}

export function fix(doc) {
  const changes = new Set()
  if (!hasChrome(doc) || hasBypass(doc)) return changes
  const body = doc.body
  if (!body) return changes
  // Wrap everything after the last top-level nav/header in <main id="main-content">.
  const chrome = [...body.children].filter((el) => /^(nav|header)$/i.test(el.tagName)
    || ['navigation', 'banner'].includes(el.getAttribute('role') || ''))
  const last = chrome.length ? chrome[chrome.length - 1] : null
  const main = doc.createElement('main')
  main.setAttribute('id', 'main-content')
  const toWrap = []
  let after = last === null
  ;[...body.children].forEach((el) => {
    if (el === last) { after = true; return }
    if (after && !/^(script|style)$/i.test(el.tagName)) toWrap.push(el)
  })
  if (!toWrap.length) return changes
  body.insertBefore(main, toWrap[0])
  toWrap.forEach((el) => main.appendChild(el))
  const skip = doc.createElement('a')
  skip.setAttribute('href', '#main-content')
  skip.setAttribute('class', 'skip-link')
  skip.textContent = 'Skip to main content'
  body.insertBefore(skip, body.firstChild)
  changes.add('Added a skip link and main landmark · 2.4.1')
  return changes
}

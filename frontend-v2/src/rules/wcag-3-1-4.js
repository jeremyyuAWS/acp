// 3.1.4 Abbreviations (Level AAA)
// A mechanism for identifying the expanded form of abbreviations is available.
// Fix: deterministic — walk all text nodes and wrap known abbreviations in <abbr title>.
//   Only wraps each abbreviation once per text node to avoid double-wrapping on re-run.

import { ABBR } from './utils.js'

export const meta = {
  id: '3.1.4',
  level: 'AAA',
  name: 'Abbreviations',
  fixMode: 'auto', // known-abbreviation dictionary is deterministic
}

const ABBR_RE = new RegExp('\\b(' + Object.keys(ABBR).join('|') + ')\\b')

export function check(doc) {
  if (!doc.body) return []
  const walker = doc.createTreeWalker(doc.body, 4 /* SHOW_TEXT */)
  const findings = []
  while (walker.nextNode()) {
    const node = walker.currentNode
    if (node.parentElement?.closest('abbr, script, style, title')) continue
    if (ABBR_RE.test(node.textContent)) {
      findings.push({ element: node.textContent.slice(0, 80), detail: 'Abbreviation without expansion', severity: 'MINOR' })
    }
  }
  return findings
}

export function fix(doc) {
  const changes = new Set()
  if (!doc.body || !Object.keys(ABBR).length) return changes
  const re = ABBR_RE
  const walker = doc.createTreeWalker(doc.body, 4 /* SHOW_TEXT */)
  const nodes = []
  while (walker.nextNode()) nodes.push(walker.currentNode)
  nodes.forEach((node) => {
    if (node.parentElement?.closest('abbr, script, style, title')) return
    let text = node.textContent
    if (!re.test(text)) return
    const frag = doc.createDocumentFragment()
    let m
    while ((m = re.exec(text))) {
      if (m.index) frag.appendChild(doc.createTextNode(text.slice(0, m.index)))
      const ab = doc.createElement('abbr')
      ab.setAttribute('title', ABBR[m[1]])
      ab.textContent = m[1]
      frag.appendChild(ab)
      text = text.slice(m.index + m[1].length)
      changes.add('Expanded abbreviations with <abbr> · 3.1.4')
    }
    if (text) frag.appendChild(doc.createTextNode(text))
    node.replaceWith(frag)
  })
  return changes
}

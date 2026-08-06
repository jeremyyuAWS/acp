// 2.4.9 Link Purpose (Link Only) (Level AAA)
// The purpose of each link is clear from its link text ALONE — no credit for
// surrounding context. 2.4.4 (A) lets context disambiguate; 2.4.9 doesn't, so
// its genuine failure case is different: identical link text pointing at
// different destinations, which 2.4.4 tolerates (context sorts it out — "Read
// more" under each of three product cards) but 2.4.9 fails outright (the text
// alone can't tell you where any one of them goes). We also catch links whose
// text is vague on its own (2.4.4's ambiguous-phrase list) — those fail "text
// alone" a fortiori, context or not.
// Fix: ai-assisted — genuinely distinguishing text needs knowing what each link
//   is about; this derives a deterministic best-effort suffix from the URL/index.

import { AMBIGUOUS_LINK } from './utils.js'

export const meta = {
  id: '2.4.9',
  level: 'AAA',
  name: 'Link Purpose (Link Only)',
  fixMode: 'ai-assisted', // derived suffixes are a starting point, not the final wording
}

const name = (a) => (a.getAttribute('aria-label') || a.textContent || '').trim().toLowerCase()

// Placeholder hrefs (JS-driven modals/toggles) aren't a "different destination" —
// excluding them avoids flooding on template links that all say href="#".
const isRealHref = (href) => Boolean(href) && href !== '#'

function ambiguousHrefs(doc) {
  const groups = new Map() // name -> Set<href>
  doc.querySelectorAll('a[href]').forEach((a) => {
    const href = a.getAttribute('href')
    const n = name(a)
    if (!isRealHref(href) || !n) return
    if (!groups.has(n)) groups.set(n, new Set())
    groups.get(n).add(href)
  })
  const bad = new Set()
  for (const hrefs of groups.values()) if (hrefs.size > 1) for (const h of hrefs) bad.add(h)
  return bad
}

export function check(doc) {
  const findings = []
  const bad = ambiguousHrefs(doc)
  doc.querySelectorAll('a[href]').forEach((a) => {
    const href = a.getAttribute('href')
    const text = (a.textContent || '').trim()
    const vague = AMBIGUOUS_LINK.test(text) && !a.getAttribute('aria-label')
    const duplicated = isRealHref(href) && bad.has(href)
    if (!vague && !duplicated) return
    findings.push({
      element: a.outerHTML.slice(0, 120),
      detail: duplicated
        ? `Link text "${text}" is reused for a different destination elsewhere — not distinguishable from text alone`
        : `Ambiguous link text "${text}" conveys no purpose without surrounding context`,
      severity: 'MODERATE',
    })
  })
  return findings
}

// Humanize the last meaningful path segment of a URL for a distinguishing
// suffix — mirrors utils.altFromSrc's approach for image filenames.
const hrefHint = (href) => {
  try {
    const path = href.replace(/^[a-z]+:\/\/[^/]+/i, '').split(/[?#]/)[0]
    const seg = path.split('/').filter(Boolean).pop()
    if (!seg) return null
    return seg.replace(/\.[^./]+$/, '').replace(/[-_]+/g, ' ').trim() || null
  } catch {
    return null
  }
}

export function fix(doc) {
  const changes = new Set()
  const bad = ambiguousHrefs(doc)
  let dupIndex = 0
  doc.querySelectorAll('a[href]').forEach((a) => {
    const href = a.getAttribute('href')
    const text = (a.textContent || '').trim()
    if (a.getAttribute('aria-label')) return // already fixed by an earlier rule/pass
    const vague = AMBIGUOUS_LINK.test(text)
    const duplicated = isRealHref(href) && bad.has(href)
    if (!vague && !duplicated) return
    if (duplicated) {
      dupIndex += 1
      const hint = hrefHint(href)
      a.setAttribute('aria-label', hint ? `${text} — ${hint}` : `${text} (${dupIndex})`)
    } else {
      a.setAttribute('aria-label', `${text} — ${doc.title || 'link'}`)
    }
    changes.add('Made link purpose clear from text alone (derived — verify) · 2.4.9')
  })
  return changes
}

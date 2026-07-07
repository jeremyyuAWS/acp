// Phase 3 — the last two AAA agentic-tier roadmap items, closed deterministically.
// 2.4.9 Link Purpose (Link Only): identical link text pointing at different
// destinations fails "text alone" even when 2.4.4 (context-aware) would pass.
import { describe, it, expect } from 'vitest'
import * as r249 from './wcag-2-4-9.js'
import * as r244 from './wcag-2-4-4.js'
import { allRules, PLAIN_NAMES } from './index.js'

const parse = (body) =>
  new DOMParser().parseFromString(`<!doctype html><html><body>${body}</body></html>`, 'text/html')

describe('registration', () => {
  it('2.4.9 is registered with a plain name', () => {
    expect(allRules.some((r) => r.meta.id === '2.4.9')).toBe(true)
    expect(PLAIN_NAMES['2.4.9']).toBeTruthy()
    expect(PLAIN_NAMES['1.4.9']).toBeTruthy() // OCR-only — no frontend module, but still named
  })
})

describe('2.4.9 Link Purpose (Link Only)', () => {
  it('flags identical link text pointing at different destinations', () => {
    const doc = parse(`
      <p><a href="/apple">View details</a></p>
      <p><a href="/banana">View details</a></p>`)
    const findings = r249.check(doc)
    expect(findings).toHaveLength(2)
  })

  it('the same case PASSES 2.4.4 (context disambiguates) — proving 2.4.9 is a stricter, distinct check', () => {
    const doc = parse(`
      <p><a href="/apple">View details</a></p>
      <p><a href="/banana">View details</a></p>`)
    expect(r244.check(doc)).toEqual([]) // "View details" isn't in 2.4.4's ambiguous-phrase list
    expect(r249.check(doc).length).toBeGreaterThan(0)
  })

  it('does not flag identical text pointing at the SAME destination', () => {
    const doc = parse(`
      <p><a href="/apple">Apple details</a></p>
      <p><a href="/apple">Apple details</a></p>`)
    expect(r249.check(doc)).toEqual([])
  })

  it('ignores href="#" placeholders (JS-driven, not a real distinct destination)', () => {
    const doc = parse(`<a href="#">Open</a><a href="#">Open</a>`)
    expect(r249.check(doc)).toEqual([])
  })

  it('flags vague link text on its own, regardless of duplication', () => {
    const doc = parse(`<a href="/only">click here</a>`)
    expect(r249.check(doc)).toHaveLength(1)
  })

  it('an aria-label already present is respected as sufficient context', () => {
    const doc = parse(`
      <p><a href="/apple" aria-label="Read more about apples">Read more</a></p>
      <p><a href="/banana" aria-label="Read more about bananas">Read more</a></p>`)
    expect(r249.check(doc)).toEqual([])
  })

  it('fix derives a distinguishing suffix and re-checks clean', () => {
    const doc = parse(`
      <p><a href="/products/apple-pie">Read more</a></p>
      <p><a href="/products/banana-bread">Read more</a></p>`)
    expect(r249.check(doc).length).toBeGreaterThan(0)
    const changes = r249.fix(doc)
    expect(changes.size).toBeGreaterThan(0)
    expect(r249.check(doc)).toEqual([])
    const labels = [...doc.querySelectorAll('a')].map((a) => a.getAttribute('aria-label'))
    expect(new Set(labels).size).toBe(2) // genuinely distinguished, not just duplicated
  })

  it('routes derived fixes to human review, not silent auto-certification', () => {
    expect(r249.meta.fixMode).toBe('ai-assisted')
  })
})

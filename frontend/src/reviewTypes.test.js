import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { reviewType, REVIEW_TYPES } from './reviewCard.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('three review types — different jobs, not one generic queue', () => {
  it('an item with a drafted value is an AI proposal review', () => {
    expect(reviewType({ rule_id: '1.1.1', proposals: [{ proposed_value: 'Bar chart of Q4 revenue' }] }))
      .toBe('proposal')
    // decorative inference drafts a concrete disposition — still a proposal to validate
    expect(reviewType({ rule_id: '1.1.1', proposals: [{ proposed_value: 'Mark as decorative — no alt text needed', kind: 'decorative' }] }))
      .toBe('proposal')
  })

  it('an auto/verify pseudo-rule row is a deterministic confirmation', () => {
    expect(reviewType({ rule_id: 'auto/verify', proposals: [] })).toBe('confirm')
    // even if a stray proposal were attached, the applied-fix row stays a confirmation
    expect(reviewType({ rule_id: 'auto/verify', proposals: [{ proposed_value: 'x' }] })).toBe('confirm')
  })

  it('a row with no draft (deferred evidence only) is manual authoring', () => {
    expect(reviewType({ rule_id: '1.1.1', proposals: [] })).toBe('author')
    expect(reviewType({ rule_id: '1.4.8' })).toBe('author')
    // empty-string drafts are not drafts — never present an empty box as "AI proposed this"
    expect(reviewType({ rule_id: '1.1.1', proposals: [{ proposed_value: '  ' }] })).toBe('author')
  })

  it('every type carries its own promise and no fabricated numbers', () => {
    for (const t of Object.values(REVIEW_TYPES)) {
      expect(t.label.length).toBeGreaterThan(0)
      expect(t.promise.length).toBeGreaterThan(0)
      expect(t.promise).not.toMatch(/\d+\s*%/)   // ADR 0016: no confidence-style percentages
    }
  })

  it('ReviewCenter partitions by type and orders sections by effort', () => {
    const src = read('ReviewCenter.jsx')
    expect(src).toMatch(/\['proposal', 'confirm', 'author'\]/)      // drafted → applied → authoring
    expect(src).toMatch(/rc-type-head rc-type-\$\{sec\.type\.key\}/) // per-type styling hook
    expect(src).toMatch(/sec\.type\.promise/)                        // the promise is rendered
    // keyboard order must follow the rendered section order, not the old flat grouping
    expect(src).toMatch(/sections\.flatMap\(\(s\) => s\.groups\.flatMap\(\(g\) => g\.items\)\)/)
  })
})

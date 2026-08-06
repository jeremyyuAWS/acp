import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { groupPages } from './reviewCard.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('vision §17 — document page heatmap in the review card', () => {
  it('groups instance indexes by measured page, sorted by page then index', () => {
    // instances 0,3 on slide 2; instance 1 on slide 5; instance 2 unresolved (absent)
    expect(groupPages({ 0: 2, 3: 2, 1: 5 })).toEqual([[2, [0, 3]], [5, [1]]])
  })

  it('is empty on empty/undefined input and drops non-numeric pages (never guesses)', () => {
    expect(groupPages({})).toEqual([])
    expect(groupPages(undefined)).toEqual([])
    expect(groupPages({ 0: 'cover', 1: 3 })).toEqual([[3, [1]]])
  })

  it('EvidenceCard renders the strip only for 2+ attributed pages and jumps the hero on click', () => {
    const src = read('EvidenceCard.jsx')
    expect(src).toMatch(/pageStrip\.length > 1 &&/)              // single-page finding → no map
    expect(src).toMatch(/onClick=\{\(\) => setHeroIdx\(idxs\[0\]\)\}/)  // click → first finding there
    expect(src).toMatch(/getFileGeometry\(item\.scan_id, item\.file, inst\.locator\)/)  // measured, not guessed
  })

  it('ReviewCenter keyboard hint matches the handler (a→approve, r→reject, s→I’ll fix it)', () => {
    const src = read('ReviewCenter.jsx')
    // The handler is the contract…
    expect(src).toMatch(/e\.key === 'r'\) \{ e\.preventDefault\(\); doAct\(cur, 'rejected'\)/)
    expect(src).toMatch(/e\.key === 's'\) \{ e\.preventDefault\(\); doAct\(cur, 'skipped'\)/)
    // …and the visible hint must say the same thing (they were swapped once).
    const hint = src.match(/rc-kbd-hint[^\n]*/)?.[0] || ''
    expect(hint).toMatch(/<b>r<\/b> reject/)
    expect(hint).toMatch(/<b>s<\/b> I’ll fix it/)
  })
})

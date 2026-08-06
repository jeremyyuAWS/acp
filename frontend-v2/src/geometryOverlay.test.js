import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { firstLocator, buildEvidenceCard } from './reviewCard.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('ADR 0018 Slice 2 — the finding carries its shape locator to the overlay', () => {
  it('firstLocator reads the proposal locator, falls back to evidence, else null', () => {
    expect(firstLocator({ proposals: [{ locator: 'ppt/slides/slide3.xml#rId4' }] }))
      .toBe('ppt/slides/slide3.xml#rId4')
    // No proposal locator → the first deferred-evidence image's locator.
    expect(firstLocator({ evidence: [{ locator: 'ppt/slides/slide2.xml#rId2', thumb: null }] }))
      .toBe('ppt/slides/slide2.xml#rId2')
    // A judgement finding / page-level PDF finding carries no shape locator → null (no box).
    for (const empty of [{}, { proposals: [] }, { proposals: null }, null]) {
      expect(firstLocator(empty)).toBeNull()
    }
  })

  it('buildEvidenceCard exposes card.locator so the hero can request the box', () => {
    const card = buildEvidenceCard({ rule_id: '1.1.1', file: 'deck.pptx',
      proposals: [{ locator: 'ppt/slides/slide3.xml#rId4', proposed_value: 'A chart.' }] })
    expect(card.locator).toBe('ppt/slides/slide3.xml#rId4')
  })
})

describe('the overlay is a measured box or nothing (ADR 0016 honesty)', () => {
  it('Thumbnail requests geometry from the locator and draws a red box only when one comes back', () => {
    const src = read('Thumbnail.jsx')
    // Fetches the box for the given locator...
    expect(src).toMatch(/getFileGeometry\(scanId, file, locator\)/)
    // ...renders the page the GEOMETRY reports (so box + picture always agree)...
    expect(src).toMatch(/const renderPage = box && box\.page \? box\.page : fallbackPage/)
    // ...and only paints the overlay when a box exists — no box ⇒ plain preview.
    expect(src).toMatch(/\{box && \(/)
    expect(src).toMatch(/className="evidence-box"/)
    // The box is positioned by the real normalized fractions, never a guess.
    expect(src).toMatch(/left: `\$\{box\.x \* 100\}%`/)
  })

  it('Slice 3 — a zoom-to-object toggle reveals a CSS crop close-up (only when a box exists)', () => {
    const src = read('Thumbnail.jsx')
    // The toggle and the crop are gated on `box` — no box, no zoom control.
    expect(src).toMatch(/\{box && \(\s*<div className="thumb-tools">/)
    expect(src).toMatch(/\{box && zoom && \(/)
    // The close-up is a pure CSS crop of the render already fetched — no second network call.
    expect(src).toMatch(/cropStyle\(url, box\)/)
    expect(src).toMatch(/backgroundSize: `\$\{100 \/ w\}%`/)
    // aria-pressed reflects the toggle state (accessible control).
    expect(src).toMatch(/aria-pressed=\{zoom\}/)
  })

  it('getFileGeometry hits the geometry endpoint and unwraps bbox (null on any miss)', () => {
    const src = read('api.js')
    expect(src).toMatch(/getFileGeometry = \(scanId, file, locator\)/)
    expect(src).toMatch(/\/geometry\?locator=\$\{encodeURIComponent\(locator\)\}/)
    expect(src).toMatch(/d && d\.bbox\) \|\| null/)
    // SIM / missing args short-circuit to no box.
    expect(src).toMatch(/SIM \|\| !scanId \|\| !file \|\| !locator/)
  })
})

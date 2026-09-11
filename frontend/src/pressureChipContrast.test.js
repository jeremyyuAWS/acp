import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const css = readFileSync(join(here, 'styles.css'), 'utf8')
const live = readFileSync(join(here, 'AdminLiveTraffic.jsx'), 'utf8')

function channel(v) {
  const n = v / 255
  return n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4
}

function luminance(hex) {
  const n = hex.replace('#', '')
  const rgb = [0, 2, 4].map((i) => channel(parseInt(n.slice(i, i + 2), 16)))
  return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
}

function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

/* Comments are stripped BEFORE any brace scanning. The token blocks below are documented in prose
   that itself contains braces — the `style={{ color }}` this fix is about, for one — and a scanner
   that counts those finds the rule ending in the middle of a sentence. Caught by this very test
   failing on its first run, which is the argument for stripping rather than for rewording. */
const declarations = css.replace(/\/\*[\s\S]*?\*\//g, '')

/** Declarations of every rule whose selector starts with `prefix`. Token blocks carry no nested
 *  braces once comments are gone, so the first `}` after the opening `{` closes the rule. */
function blocks(prefix) {
  const out = []
  let i = 0
  while ((i = declarations.indexOf(prefix, i)) !== -1) {
    const open = declarations.indexOf('{', i)
    const close = declarations.indexOf('}', open)
    out.push(declarations.slice(open + 1, close))
    i = close
  }
  return out
}

function pressureTokens(block) {
  const found = {}
  for (const [, name, hex] of block.matchAll(/--pressure-([a-z]+):\s*(#[0-9A-Fa-f]{6})/g)) {
    found[name] = hex
  }
  return found
}

const STANDARD = pressureTokens(blocks(':root {').find((b) => b.includes('--pressure-')))
const WCAG = pressureTokens(blocks('[data-wcag="on"] {').find((b) => b.includes('--pressure-')))

const STATES = ['healthy', 'busy', 'saturated', 'stalled']
const CHIP_BG = '#ffffff' // `.chip { background: #fff }` — the chip paints its own ground

describe('Live Operations pressure chip contrast', () => {
  it('defines all four states in both palettes', () => {
    expect(Object.keys(STANDARD).sort()).toEqual([...STATES].sort())
    expect(Object.keys(WCAG).sort()).toEqual([...STATES].sort())
  })

  // The chip is `font-size: 12px`, which is NOT WCAG "large text" (18pt / 14pt bold), so the
  // threshold is 4.5:1 and not 3:1. Getting this wrong is how #A66A16 survived review: at the
  // large-text threshold it passes comfortably, and at the real one it misses by 0.03.
  it.each(STATES)('standard %s passes AA for 12px text on the chip', (state) => {
    expect(contrast(STANDARD[state], CHIP_BG)).toBeGreaterThanOrEqual(4.5)
  })

  it.each(STATES)('high-contrast %s reaches 7:1', (state) => {
    expect(contrast(WCAG[state], CHIP_BG)).toBeGreaterThanOrEqual(7)
  })

  it('never regresses: the high-contrast value is at least as dark as the standard one', () => {
    for (const state of STATES) {
      expect(contrast(WCAG[state], CHIP_BG)).toBeGreaterThanOrEqual(contrast(STANDARD[state], CHIP_BG))
    }
  })

  /* The specific value this test was written for. Naming it means a revert reads as a deliberate
     act with a red test beside it, rather than as a colour tweak nobody measured.

     SCOPED TO PRESSURE ON PURPOSE. The same #A66A16 is still STAGE.release in this module, and
     that is correct, not an oversight: STAGE colours are borders, graph edges and node accents —
     non-text, where 1.4.11 asks 3:1 and 4.47:1 clears it comfortably. The identical hex fails in
     one map and passes in the other because the threshold follows the USE, not the colour. Do not
     "finish the job" by purging this value module-wide without re-measuring each consumer. */
  it('does not restore the amber that failed', () => {
    expect(contrast('#A66A16', CHIP_BG)).toBeLessThan(4.5)        // 4.47:1 — fails AA as text
    expect(contrast('#A66A16', CHIP_BG)).toBeGreaterThanOrEqual(3) // …and passes as non-text
    expect(Object.values(STANDARD)).not.toContain('#A66A16')
    expect(Object.values(WCAG)).not.toContain('#A66A16')
  })

  // Four states distinguished by colour must stay distinguishable from each other, or tightening
  // for contrast quietly collapses two states into one indicator. Labels carry the real meaning
  // (colour is never the only channel here), but a palette that renders "Work waiting" and
  // "At capacity" identically is still a defect.
  it('keeps the four states visually distinct in both palettes', () => {
    for (const palette of [STANDARD, WCAG]) {
      expect(new Set(Object.values(palette)).size).toBe(STATES.length)
    }
  })

  /* THE STRUCTURAL GUARD, and the reason the colour fix alone was not enough.
     These colours reach the DOM through an inline `style={{ color }}`. An inline declaration
     outranks every selector, so while the PRESSURE map held hex literals no [data-wcag="on"]
     rule could override them: the toggle was on, and this chip did not change. A future hex
     literal here would silently reopen exactly that hole, and would do it while the palette
     menu still promised "accessible colours across every tab". */
  it('colours the PRESSURE map with tokens, never hex literals', () => {
    // To the map's OWN terminator — the `}` in column 0 — not the first `}` in the text, which
    // closes the `healthy` entry and would leave the other three states unexamined.
    const map = live.slice(live.indexOf('const PRESSURE = {'))
    const body = map.slice(0, map.indexOf('\n}'))
    expect(body.match(/label:/g)).toHaveLength(STATES.length) // the slice really spans all four
    expect(body).not.toMatch(/#[0-9A-Fa-f]{3,6}/)
    for (const state of STATES) {
      expect(body).toContain(`var(--pressure-${state})`)
    }
  })
})

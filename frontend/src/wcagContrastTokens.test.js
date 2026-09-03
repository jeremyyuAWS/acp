/**
 * WCAG contrast-token verification.
 *
 * Every semantic CSS custom property that is defined in :root (or overridden in
 * [data-wcag="on"]) gets its foreground/background pair verified here.  Failures
 * in this file mean a variable was changed to a value that no longer meets the
 * threshold that applies to the elements that use it.
 *
 * Thresholds (WCAG 2.1 AA):
 *   4.5 : 1 — normal text (any size without the large-text exemption)
 *   3.0 : 1 — large text (≥ 18pt / ≥ 14pt bold) and non-text UI controls
 *
 * This file does NOT mount any React component; it is a pure arithmetic check
 * on the token values documented in styles.css :root and [data-wcag="on"].
 */
import { describe, it, expect } from 'vitest'

// --- WCAG contrast math ---------------------------------------------------

function linearize(channel) {
  const c = channel / 255
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
}

function relativeLuminance(hex) {
  const h = hex.replace('#', '')
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)
}

function contrastRatio(fg, bg) {
  const l1 = relativeLuminance(fg)
  const l2 = relativeLuminance(bg)
  const lighter = Math.max(l1, l2)
  const darker = Math.min(l1, l2)
  return (lighter + 0.05) / (darker + 0.05)
}

// --- Token definitions (must match styles.css :root and [data-wcag="on"]) --

const STANDARD = {
  '--plum':          '#46303F',
  '--ink':           '#2b2330',
  '--muted':         '#6c6470',
  '--bg':            '#faf8fb',
  '--card':          '#ffffff',
  '--line':          '#ece8ee',
  '--focus-ring':    '#7a5c8e',
  '--text-secondary':'#9aa2ac',
  '--text-disabled': '#B9B4C0',
}

const WCAG = {
  ...STANDARD,
  '--muted':          '#595060',
  '--text-secondary': '#5c6570',
  '--text-disabled':  '#716b76',
}

// --- Semantic pairs -----------------------------------------------------------
//
// Each entry: [token-fg, background-hex, description, min-ratio]
//   background-hex is either a literal or the name of a token to look up.
//   min-ratio: 4.5 for normal text, 3.0 for large text / non-text controls.

const STANDARD_PAIRS = [
  // Established tokens that must not regress
  ['--plum',    '#ffffff',   '--plum on white (brand text/buttons)',            4.5],
  ['--ink',     '--bg',      '--ink on --bg (primary body text)',               4.5],
  ['--muted',   '--bg',      '--muted on --bg (secondary body text)',           4.5],
  ['--muted',   '#ffffff',   '--muted on white card (secondary text)',          4.5],
  ['--focus-ring','#ffffff', '--focus-ring on white (keyboard focus indicator)',3.0],
  // New tokens — standard mode may fail; these get the WCAG override
  // (documented here as evidence of why the override is needed, not as regressions)
  ['--text-secondary','#f7f9fb','--text-secondary on atile bg (denominator text, standard)',null],
  ['--text-disabled', '#ffffff','--text-disabled on white (pending state, standard)',        null],
]

const WCAG_PAIRS = [
  ['--plum',    '#ffffff',   '--plum on white (WCAG mode)',                     4.5],
  ['--ink',     '--bg',      '--ink on --bg (WCAG mode)',                       4.5],
  ['--muted',   '--bg',      '--muted on --bg (WCAG override)',                 4.5],
  ['--muted',   '#ffffff',   '--muted on white (WCAG override)',                4.5],
  ['--focus-ring','#ffffff', '--focus-ring on white (WCAG mode)',               3.0],
  ['--text-secondary','#f7f9fb','--text-secondary on atile bg (WCAG override)', 4.5],
  ['--text-disabled', '#ffffff','--text-disabled on white (WCAG override)',     4.5],
]

function resolve(tokenOrHex, tokens) {
  return tokenOrHex.startsWith('--') ? tokens[tokenOrHex] : tokenOrHex
}

// --- Tests -------------------------------------------------------------------

describe('standard-mode token regressions', () => {
  STANDARD_PAIRS.forEach(([fg, bg, label, min]) => {
    if (min === null) return  // intentional standard-mode fail; tested in WCAG suite
    it(`${label} ≥ ${min}:1`, () => {
      const fgHex = resolve(fg, STANDARD)
      const bgHex = resolve(bg, STANDARD)
      const ratio = contrastRatio(fgHex, bgHex)
      expect(ratio, `${fgHex} on ${bgHex} = ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(min)
    })
  })
})

describe('WCAG-mode token overrides — all semantic pairs must reach their threshold', () => {
  WCAG_PAIRS.forEach(([fg, bg, label, min]) => {
    it(`${label} ≥ ${min}:1`, () => {
      const fgHex = resolve(fg, WCAG)
      const bgHex = resolve(bg, WCAG)
      const ratio = contrastRatio(fgHex, bgHex)
      expect(ratio, `${fgHex} on ${bgHex} = ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(min)
    })
  })
})

describe('WCAG-mode standard-fail tokens — verify they improve', () => {
  it('--text-secondary improves from standard to WCAG mode', () => {
    const bg = '#f7f9fb'
    const stdRatio  = contrastRatio(STANDARD['--text-secondary'], bg)
    const wcagRatio = contrastRatio(WCAG['--text-secondary'], bg)
    expect(stdRatio,  'standard --text-secondary should be below 4.5:1').toBeLessThan(4.5)
    expect(wcagRatio, 'WCAG --text-secondary must reach 4.5:1').toBeGreaterThanOrEqual(4.5)
  })

  it('--text-disabled improves from standard to WCAG mode', () => {
    const bg = '#ffffff'
    const stdRatio  = contrastRatio(STANDARD['--text-disabled'], bg)
    const wcagRatio = contrastRatio(WCAG['--text-disabled'], bg)
    expect(stdRatio,  'standard --text-disabled should be below 4.5:1').toBeLessThan(4.5)
    expect(wcagRatio, 'WCAG --text-disabled must reach 4.5:1').toBeGreaterThanOrEqual(4.5)
  })
})

describe('livedot and aibadge overrides (from PR #1222, regression-pinned)', () => {
  it('livedot WCAG color on --bg ≥ 4.5:1', () => {
    expect(contrastRatio('#7A5000', STANDARD['--bg'])).toBeGreaterThanOrEqual(4.5)
  })
  it('aibadge.off WCAG background gives white text ≥ 4.5:1', () => {
    expect(contrastRatio('#ffffff', '#6b6470')).toBeGreaterThanOrEqual(4.5)
  })
})

// ACP's own UI must pass the criterion ACP certifies documents against.
//
// The app bundles axe-core and ships a self-check (A11ySelfCheck.jsx). On 2026-07-29 that
// self-check reported 23 WCAG 1.4.3 failures in ACP's own interface — 16-20 on Remediate,
// 19 on Discover, 4 on Publish. Every one had the same cause, and it was never the colour:
//
//   opacity applied to TEXT.
//
// Opacity blends the ink toward whatever is behind it, so a token chosen to pass at 5.68:1
// renders at 2.75:1 and no palette review ever catches it — the hex in the stylesheet is still
// correct. De-emphasis has to be expressed as a colour (or weight/size), never as transparency.
//
// This file guards both halves: the tokens are actually compliant, and the three sites that
// dimmed them do not come back. (A fourth — the retired "Remediation plan" band's buttons — went
// away with the band itself.)
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const src = (f) => readFileSync(join(here, f), 'utf8')
// Comment-stripped, so an assertion about the CODE is not satisfied — or broken — by prose
// about it. These fixes are heavily commented with the very words being asserted against.
const code = (f) => src(f)
  .split('\n')
  .filter((l) => { const t = l.trim(); return !t.startsWith('//') && !t.startsWith('*') && !t.startsWith('/*') && !t.startsWith('{/*') })
  .join('\n')

// WCAG 2.1 relative luminance + contrast ratio (§1.4.3).
const rgb = (h) => {
  let s = h.replace('#', '')
  if (s.length === 3) s = [...s].map((c) => c + c).join('')
  return [0, 2, 4].map((i) => parseInt(s.slice(i, i + 2), 16))
}
const lum = (c) => {
  const s = c.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4 })
  return 0.2126 * s[0] + 0.7152 * s[1] + 0.0722 * s[2]
}
export const contrast = (fg, bg) => {
  const [a, b] = [lum(rgb(fg)), lum(rgb(bg))]
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}
// What opacity actually does to the rendered ink — the step the stylesheet hides.
const flatten = (fg, bg, alpha) => {
  const [f, b] = [rgb(fg), rgb(bg)]
  return '#' + f.map((v, i) => Math.round(alpha * v + (1 - alpha) * b[i])
    .toString(16).padStart(2, '0')).join('')
}

const AA_NORMAL = 4.5   // 1.4.3 for text under 18.66px bold / 24px regular. All of ours is.

describe('the contrast maths itself', () => {
  it('agrees with the known anchors', () => {
    expect(contrast('#000000', '#ffffff')).toBeCloseTo(21, 1)
    expect(contrast('#ffffff', '#ffffff')).toBeCloseTo(1, 5)
  })

  it('reproduces the failures axe reported, from the token + the opacity', () => {
    // .sfn — the worst one, and the one no palette review would have found.
    expect(contrast('#6c6470', '#ffffff')).toBeGreaterThan(AA_NORMAL)      // the token: 5.68
    expect(contrast(flatten('#6c6470', '#ffffff', 0.65), '#ffffff')).toBeLessThan(AA_NORMAL)  // rendered: 2.75
    // the ladder's not-yet-reached step
    expect(contrast(flatten('#2b2330', '#ffffff', 0.55), '#ffffff')).toBeLessThan(AA_NORMAL)  // 3.57
    // the risk chip's "· est N min" suffix
    expect(contrast(flatten('#b43a2a', '#fbe7e2', 0.85), '#fbe7e2')).toBeLessThan(AA_NORMAL)  // 3.85
    // the Accept-full-plan sub-label
    expect(contrast(flatten('#ffffff', '#a56814', 0.85), '#a56814')).toBeLessThan(AA_NORMAL)  // 3.78
  })
})

describe('every colour ACP puts text in clears 4.5:1', () => {
  const css = src('styles.css')
  const token = (name) => css.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{3,6})`))?.[1]

  it('the muted token — the app\'s default secondary text', () => {
    expect(contrast(token('--muted'), '#ffffff')).toBeGreaterThanOrEqual(AA_NORMAL)
  })

  it('the ink token', () => {
    expect(contrast(token('--ink'), '#ffffff')).toBeGreaterThanOrEqual(AA_NORMAL)
  })

  it('the confidence badges, each on its own background', () => {
    for (const [fg, bg] of [['#3B6D11', '#E7F0DC'], ['#8A5A00', '#FDF3E0'], ['#575360', '#ECECEF']]) {
      expect(contrast(fg, bg)).toBeGreaterThanOrEqual(AA_NORMAL)
    }
  })

  it('the risk chips, at full opacity', () => {
    expect(contrast('#B43A2A', '#FBE7E2')).toBeGreaterThanOrEqual(AA_NORMAL)
    expect(contrast('#8A5A00', '#FBEECB')).toBeGreaterThanOrEqual(AA_NORMAL)
  })

  it('white on the two primary action buttons', () => {
    expect(contrast('#ffffff', '#1F5FA8')).toBeGreaterThanOrEqual(AA_NORMAL)
    // 4.58 — passes, with almost no headroom. Anything that lightens this fails.
    expect(contrast('#ffffff', '#A56814')).toBeGreaterThanOrEqual(AA_NORMAL)
  })

  it('the excluded-row note added for the scope badge', () => {
    expect(contrast('#8A2A20', '#ffffff')).toBeGreaterThanOrEqual(AA_NORMAL)
  })
})

describe('the three sites that dimmed text do not come back', () => {
  it('.sfn is coloured, not transparent', () => {
    expect(code('styles.css')).toMatch(/\.sfn \{ color: var\(--muted\)/)
    expect(code('styles.css')).not.toMatch(/\.sfn \{[^}]*opacity/)
  })

  it('the verification ladder dims a future step by colour', () => {
    const f = code('EvidenceCard.jsx')
    expect(f).toMatch(/s\.state === 'todo' \? \{ color: 'var\(--muted\)' \}/)
    expect(f).not.toMatch(/s\.state === 'todo' \? \{ opacity/)
  })

  it('the risk chip suffix uses weight alone', () => {
    const f = code('RiskChip.jsx')
    expect(f).toMatch(/<span style=\{\{ fontWeight: 500 \}\}>· est/)
    expect(f).not.toMatch(/opacity/)
  })
})

import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const css = readFileSync(join(here, 'styles.css'), 'utf8')
const app = readFileSync(join(here, 'App.jsx'), 'utf8')

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

describe('app-wide high-contrast palette', () => {
  it('uses audited normal-text pairs and a 3:1 UI boundary', () => {
    expect(contrast('#18131a', '#ffffff')).toBeGreaterThanOrEqual(4.5)
    expect(contrast('#ffffff', '#321d2b')).toBeGreaterThanOrEqual(4.5)
    expect(contrast('#4d4551', '#ffffff')).toBeGreaterThanOrEqual(4.5)
    expect(contrast('#003f73', '#ffffff')).toBeGreaterThanOrEqual(4.5)
    expect(contrast('#59515d', '#ffffff')).toBeGreaterThanOrEqual(3)
  })

  it('scopes text, controls, focus, disabled states, notices and charts across the app', () => {
    expect(css).toContain('body *:not(svg):not(svg *)')
    expect(css).toMatch(/input, select, textarea/)
    expect(css).toMatch(/button:disabled/)
    expect(css).toMatch(/\[role="alert"\], \[role="status"\]/)
    expect(css).toMatch(/:focus-visible/)
    expect(css).toMatch(/svg text/)
  })

  it('keeps the standard palette opt-out and describes this honestly as a colour mode', () => {
    expect(app).toContain("localStorage.getItem('acp-wcag-mode') === 'on'")
    expect(app).toContain('Use high-contrast colour palette across every tab')
    expect(app).toContain('Use standard colour palette across every tab')
    expect(app).not.toContain('all UI colours meet 4.5:1 contrast')
  })
})

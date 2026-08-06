import { describe, it, expect } from 'vitest'
import fs from 'fs'
import { prescreenHtml } from './prescreen.js'

describe('prescreenHtml (Phase 2 · HITL detect-and-route)', () => {
  const html = fs.readFileSync('public/samples/careers-landing.html', 'utf8')
  const flags = prescreenHtml(html)
  const wcags = flags.map((f) => f.wcag)

  it('flags runtime/interactive risks for human review', () => {
    expect(flags.length).toBeGreaterThan(0)
    expect(wcags.some((w) => /2\.1\.4/.test(w))).toBe(true) // onkeydown trapTab
    expect(wcags.some((w) => /3\.3\.1/.test(w))).toBe(true) // form, no error structure
    expect(wcags.some((w) => /4\.1\.3/.test(w))).toBe(true) // no aria-live
  })
  it('routes every flag to a human (never auto)', () => {
    expect(flags.every((f) => f.route === 'human' && f.auto === false)).toBe(true)
    flags.forEach((f) => expect(f.detail).toMatch(/confirm|human|needs/i))
  })
  it('returns [] on empty / odd input without throwing', () => {
    expect(prescreenHtml('')).toEqual([])
    expect(() => prescreenHtml(null)).not.toThrow()
  })
})

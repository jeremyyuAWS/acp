// Round-trip guarantee for the three re-worked rule modules: whatever check()
// flags, fix() must repair such that a re-check comes back clean — a "fixed"
// document that still fails its own check would re-flag on the next scan.
import { describe, it, expect } from 'vitest'
import * as r211 from './wcag-2-1-1.js'
import * as r141 from './wcag-1-4-1.js'
import * as r131 from './wcag-1-3-1.js'

const parse = (body) =>
  new DOMParser().parseFromString(
    `<!doctype html><html><body>${body}</body></html>`,
    'text/html'
  )

const roundTrip = (mod, body) => {
  const doc = parse(body)
  expect(mod.check(doc).length).toBeGreaterThan(0)
  expect(mod.fix(doc).size).toBeGreaterThan(0)
  expect(mod.check(doc)).toEqual([])
  return doc
}

describe('2.1.1 Keyboard', () => {
  it('adds activation, not just focusability (round-trip clean)', () => {
    const doc = roundTrip(r211, `<div onclick="go()">card</div>`)
    const el = doc.querySelector('div')
    expect(el.getAttribute('tabindex')).toBe('0')
    expect(el.getAttribute('role')).toBe('button')
    expect(el.getAttribute('onkeydown')).toMatch(/Enter/)
    expect(el.getAttribute('onkeydown')).toMatch(/click\(\)/)
  })

  it('still flags focusable-but-inert elements (the old fix output)', () => {
    const doc = parse(`<span onclick="go()" tabindex="0" role="button">x</span>`)
    expect(r211.check(doc)).toHaveLength(1)
  })

  it('does not clobber an existing keydown handler', () => {
    const doc = roundTrip(r211, `<div onclick="go()" onkeydown="mine()">x</div>`)
    expect(doc.querySelector('div').getAttribute('onkeydown')).toBe('mine()')
  })

  it('normalizes tabindex="-1" (focus-excluded) to 0', () => {
    const doc = roundTrip(r211, `<div onclick="go()" tabindex="-1">x</div>`)
    expect(doc.querySelector('div').getAttribute('tabindex')).toBe('0')
  })

  it('leaves native interactive elements alone', () => {
    const doc = parse(`<button onclick="go()">ok</button><a href="#" onclick="go()">a</a>`)
    expect(r211.check(doc)).toEqual([])
    expect(r211.fix(doc).size).toBe(0)
  })
})

describe('1.4.1 Use of Color', () => {
  it('underlines color-only links and re-checks clean', () => {
    const doc = roundTrip(r141, `<p><a href="#" style="color:#2E72C9">go</a></p>`)
    expect(doc.querySelector('a').getAttribute('style')).toMatch(/text-decoration:underline/)
  })

  it('replaces an explicit text-decoration:none instead of stacking a conflict', () => {
    const doc = roundTrip(
      r141,
      `<p><a href="#" style="color:red; text-decoration: none">go</a></p>`
    )
    const s = doc.querySelector('a').getAttribute('style')
    expect(s).toMatch(/text-decoration:underline/i)
    expect(s).not.toMatch(/none/)
  })

  it('catches styled links outside p/li/td (old selector gap)', () => {
    roundTrip(r141, `<div><a href="#" style="color:teal">go</a></div>`)
    roundTrip(r141, `<h2><a href="#" style="color:teal">go</a></h2>`)
  })

  it('ignores background-color, already-underlined, and unstyled links', () => {
    const doc = parse(`
      <p><a href="#" style="background-color:yellow">bg</a></p>
      <p><a href="#" style="color:red; text-decoration:underline">u</a></p>
      <p><a href="#">plain</a></p>`)
    expect(r141.check(doc)).toEqual([])
    expect(r141.fix(doc).size).toBe(0)
  })
})

describe('1.3.1 Info and Relationships', () => {
  it('labels unlabeled fields from placeholder and re-checks clean', () => {
    const doc = roundTrip(r131, `<form><input type="email" placeholder="Work email"></form>`)
    expect(doc.querySelector('input').getAttribute('aria-label')).toBe('Work email')
  })

  it('respects an implicit wrapping label (no aria-label override)', () => {
    const doc = parse(`<label>Full name <input type="text" name="fld_1"></label>`)
    expect(r131.check(doc)).toEqual([])
    r131.fix(doc)
    expect(doc.querySelector('input').hasAttribute('aria-label')).toBe(false)
  })

  it('respects an explicit label[for]', () => {
    const doc = parse(`<label for="em">Email</label><input id="em" type="email">`)
    expect(r131.check(doc)).toEqual([])
  })

  it('skips hidden inputs and self-naming buttons', () => {
    const doc = parse(`<input type="hidden" name="csrf"><input type="submit" value="Send">`)
    expect(r131.check(doc)).toEqual([])
    expect(r131.fix(doc).size).toBe(0)
  })

  it('humanizes name-attr field codes', () => {
    const doc = roundTrip(r131, `<input name="billing_zip-code">`)
    expect(doc.querySelector('input').getAttribute('aria-label')).toBe('billing zip code')
  })

  it('routes derived labels to human review, not silent auto-certification', () => {
    expect(r131.meta.fixMode).toBe('ai-assisted')
  })
})

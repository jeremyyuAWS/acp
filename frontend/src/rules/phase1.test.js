// Round-trip guarantee for the Phase 1 rule modules (1.4.2, 1.3.5, 2.5.3,
// 2.4.1, 3.3.2, 1.3.4, 1.4.6): whatever check() flags, fix() must repair such
// that a re-check comes back clean.
import { describe, it, expect } from 'vitest'
import * as r142 from './wcag-1-4-2.js'
import * as r135 from './wcag-1-3-5.js'
import * as r253 from './wcag-2-5-3.js'
import * as r241 from './wcag-2-4-1.js'
import * as r332 from './wcag-3-3-2.js'
import * as r134 from './wcag-1-3-4.js'
import * as r146 from './wcag-1-4-6.js'
import { allRules, PLAIN_NAMES } from './index.js'

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

describe('registration', () => {
  it('all Phase 1 modules are registered with plain names', () => {
    const ids = new Set(allRules.map((r) => r.meta.id))
    for (const sc of ['1.4.2', '1.3.5', '2.5.3', '2.4.1', '3.3.2', '1.3.4', '1.4.6']) {
      expect(ids.has(sc)).toBe(true)
      expect(PLAIN_NAMES[sc]).toBeTruthy()
    }
  })
})

describe('1.4.2 Audio Control', () => {
  it('removes autoplay and adds controls (round-trip clean)', () => {
    const doc = roundTrip(r142, `<video autoplay src="promo.mp4"></video>`)
    const v = doc.querySelector('video')
    expect(v.hasAttribute('autoplay')).toBe(false)
    expect(v.hasAttribute('controls')).toBe(true)
  })

  it('leaves controlled or non-autoplaying media alone', () => {
    const doc = parse(`<audio autoplay controls></audio><video src="v.mp4"></video>`)
    expect(r142.check(doc)).toEqual([])
    expect(r142.fix(doc).size).toBe(0)
  })
})

describe('1.3.5 Identify Input Purpose', () => {
  it('adds the matching autocomplete token (round-trip clean)', () => {
    const doc = roundTrip(r135, `<input type="email" name="work_email">`)
    expect(doc.querySelector('input').getAttribute('autocomplete')).toBe('email')
  })

  it('maps name-attr patterns (zip → postal-code), including keyword-final names', () => {
    const doc = roundTrip(r135, `<input name="billing_zip_code">`)
    expect(doc.querySelector('input').getAttribute('autocomplete')).toBe('postal-code')
    const doc2 = roundTrip(r135, `<input name="billing_zip">`)
    expect(doc2.querySelector('input').getAttribute('autocomplete')).toBe('postal-code')
  })

  it('does not guess on unrecognizable fields or override existing tokens', () => {
    const doc = parse(`<input name="fld_23"><input type="email" autocomplete="off">`)
    expect(r135.check(doc)).toEqual([])
    expect(r135.fix(doc).size).toBe(0)
  })
})

describe('2.5.3 Label in Name', () => {
  it('rebuilds the accessible name to start with the visible text', () => {
    const doc = roundTrip(r253, `<button aria-label="submit-form-primary">Send request</button>`)
    expect(doc.querySelector('button').getAttribute('aria-label')).toMatch(/^Send request/)
  })

  it('accepts names that already contain the visible text; ignores icon-only controls', () => {
    const doc = parse(`
      <button aria-label="Send request now">Send request</button>
      <button aria-label="Close dialog">✕</button>`)
    expect(r253.check(doc)).toHaveLength(1)   // ✕ is visible text not in the name — flagged
    r253.fix(doc)
    expect(r253.check(doc)).toEqual([])
  })
})

describe('2.4.1 Bypass Blocks', () => {
  it('adds a skip link + main landmark when nav exists (round-trip clean)', () => {
    const doc = roundTrip(r241, `<nav><a href="/a">A</a></nav><h1>Doc</h1><p>Body</p>`)
    expect(doc.querySelector('main#main-content')).toBeTruthy()
    expect(doc.querySelector('a[href="#main-content"]')).toBeTruthy()
    expect(doc.querySelector('main h1')).toBeTruthy()      // content moved inside main
    expect(doc.querySelector('main nav')).toBeNull()       // chrome stays outside
  })

  it('does not flag plain documents without repeated chrome, or pages with main', () => {
    const doc = parse(`<h1>Doc</h1><p>Body</p>`)
    expect(r241.check(doc)).toEqual([])
    const doc2 = parse(`<nav></nav><main><p>x</p></main>`)
    expect(r241.check(doc2)).toEqual([])
  })
})

describe('3.3.2 Labels or Instructions', () => {
  it('flags required fields with no guidance and derives one (round-trip clean)', () => {
    const doc = roundTrip(r332, `<input required name="billing_zip">`)
    expect(doc.querySelector('input').getAttribute('aria-label')).toBe('billing zip (required)')
  })

  it('routes derived instructions to human review', () => {
    expect(r332.meta.fixMode).toBe('ai-assisted')
  })

  it('accepts any existing guidance (label, placeholder, describedby)', () => {
    const doc = parse(`
      <label>Zip <input required></label>
      <input required placeholder="ZIP code">
      <input required aria-describedby="hint"><span id="hint">5 digits</span>
      <input name="optional_field">`)
    expect(r332.check(doc)).toEqual([])
  })
})

describe('1.3.4 Orientation', () => {
  it('neutralizes the orientation lock (round-trip clean)', () => {
    const doc = roundTrip(r134,
      `<style>@media (orientation: portrait) { .content { display: none; } }</style><div class="content">x</div>`)
    expect(doc.querySelector('style').textContent).not.toMatch(/display\s*:\s*none/)
  })

  it('ignores orientation queries that merely restyle', () => {
    const doc = parse(`<style>@media (orientation: landscape) { .content { font-size: 18px; } }</style>`)
    expect(r134.check(doc)).toEqual([])
  })
})

describe('1.4.6 Contrast (Enhanced)', () => {
  it('darkens mid-greys that pass 4.5:1 but fail 7:1 (round-trip clean)', () => {
    const doc = roundTrip(r146, `<p style="color:#767676">AA-passing grey</p>`)
    expect(doc.querySelector('p').getAttribute('style')).toMatch(/#333333/)
  })

  it('accepts colors already meeting 7:1', () => {
    const doc = parse(`<p style="color:#595959">dark enough</p>`)
    expect(r146.check(doc)).toEqual([])
  })
})

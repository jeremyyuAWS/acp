import { describe, it, expect } from 'vitest'
import { remediateHtml } from './BeforeAfter.jsx'

const SRC = `<!doctype html><html><head>
<meta name="viewport" content="width=device-width, user-scalable=no">
</head><body>
<h1>Welcome to UTSW</h1>
<img src="team-photo.png" width="200">
<p style="color:#cccccc">Faint copy with an <a href="#" style="color:#2E72C9">inline link</a>.</p>
<div onclick="go()">clickable card</div>
<form><input type="email" placeholder="Your email"></form>
<a href="#">click here</a>
<button tabindex="4">Submit</button>
<div style="border:1px solid #dddddd"><p style="line-height:12px">Tight spaced text.</p></div>
</body></html>`

describe('remediateHtml', () => {
  const { html, changes } = remediateHtml(SRC)
  const changed = (re) => changes.some((c) => re.test(c))

  it('returns fixed markup + a change log', () => {
    expect(html).toMatch(/^<!doctype html>/i)
    expect(Array.isArray(changes)).toBe(true)
    expect(changes.length).toBeGreaterThan(6)
  })

  it('sets language and a title (3.1.1 / 2.4.2)', () => {
    expect(html).toMatch(/<html[^>]*lang="en"/i)
    expect(html).toMatch(/<title>Welcome to UTSW<\/title>/)
    expect(changed(/language/i)).toBe(true)
    expect(changed(/title/i)).toBe(true)
  })

  it('adds alt text and labels form fields (1.1.1 / 1.3.1)', () => {
    expect(html).toMatch(/<img[^>]*alt="[^"]+"/i)
    expect(html).toMatch(/<input[^>]*aria-label="[^"]+"/i)
  })

  it('darkens low-contrast inline text (1.4.3)', () => {
    expect(html).toMatch(/#333333/)
    expect(changed(/contrast|darken/i)).toBe(true)
  })

  it('re-enables zoom and resets positive tabindex (1.4.4 / 2.4.3)', () => {
    expect(html).not.toMatch(/user-scalable\s*=\s*no/i)
    expect(html).not.toMatch(/tabindex="[1-9]/)
    expect(html).toMatch(/tabindex="0"/)
    expect(changed(/zoom|resize/i)).toBe(true)
    expect(changed(/focus order|tabindex/i)).toBe(true)
  })

  it('makes click-only elements keyboard-operable and underlines in-text links (2.1.1 / 1.4.1)', () => {
    expect(html).toMatch(/<div[^>]*role="button"/i)
    expect(html).toMatch(/text-decoration:underline/i)
    expect(changed(/keyboard/i)).toBe(true)
    expect(changed(/colour|color/i)).toBe(true)
  })

  it('darkens low-contrast borders and unblocks text spacing (1.4.11 / 1.4.12)', () => {
    expect(html).toMatch(/border:\s*1px solid #767676/i)
    expect(html).not.toMatch(/#dddddd/i)
    expect(html).toMatch(/line-height:\s*1\.5/)
    expect(html).not.toMatch(/line-height:\s*12px/)
    expect(changed(/non-text|border/i)).toBe(true)
    expect(changed(/spacing/i)).toBe(true)
  })

  it('clarifies ambiguous links (2.4.4)', () => {
    expect(changed(/ambiguous|clarif/i)).toBe(true)
    expect(html).toMatch(/aria-label="click here/i)
  })

  it('does not throw on odd input', () => {
    expect(() => remediateHtml('<p>unclosed')).not.toThrow()
    expect(() => remediateHtml(null)).not.toThrow()
    expect(remediateHtml('<p>x</p>')).toHaveProperty('changes')
  })
})

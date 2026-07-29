// 2.4.6 / 1.3.1 taxonomy — the html module and the backend must file the same signal under
// the same criterion.
//
// wcag-2-4-6.js used to promote visually-styled pseudo-headings, while docx filed that
// identical signal under 1.3.1 (office_structure.DOCX_PSEUDO_HEADING). One criterion, two
// answers, depending only on which format was uploaded. The pseudo-heading check now lives
// on the backend under 1.3.1 (scanner.HTML_PSEUDO_HEADING), and this module checks what
// 2.4.6 on html actually means: skipped heading levels, mirroring scanner.HTML_HEADING_SKIP
// and remediate._fix_heading_skip.
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, it, expect } from 'vitest'
import * as r246 from './wcag-2-4-6.js'
import { allRules } from './index.js'

const parse = (body) =>
  new DOMParser().parseFromString(`<!doctype html><html><body>${body}</body></html>`, 'text/html')

const repoFile = (rel) => {
  let dir = process.cwd()
  for (let i = 0; i < 6; i++) {
    const p = path.join(dir, rel)
    try { readFileSync(p); return p } catch { dir = path.dirname(dir) }
  }
  throw new Error(`repo file not found: ${rel}`)
}

describe('2.4.6 taxonomy', () => {
  it('is still registered, and still the only 2.4.6 module', () => {
    expect(allRules.filter((r) => r.meta.id === '2.4.6')).toHaveLength(1)
  })

  it('no longer promotes pseudo-headings — that signal is 1.3.1 now', () => {
    const doc = parse(`<p style="font-size:24px;font-weight:bold">Quarterly Results</p>`)
    expect(r246.check(doc)).toEqual([])
    r246.fix(doc)
    expect(doc.querySelectorAll('h2')).toHaveLength(0)
    expect(doc.querySelector('p')).not.toBeNull()
  })

  it('the backend files pseudo-headings under 1.3.1, and this module never mentions 2.4.6 for them', () => {
    const scanner = readFileSync(repoFile('api/scanner.py'), 'utf8')
    // The rule id and its criterion must sit on the same statement as 1.3.1, not 2.4.6.
    expect(scanner).toMatch(/HTML_PSEUDO_HEADING",\s*"wcag":\s*"1\.3\.1/)
    expect(scanner).not.toMatch(/HTML_PSEUDO_HEADING",\s*"wcag":\s*"2\.4\.6/)
  })
})

describe('2.4.6 heading level skips', () => {
  it('flags a skipped level', () => {
    const findings = r246.check(parse('<h1>One</h1><h3>Three</h3>'))
    expect(findings).toHaveLength(1)
    expect(findings[0].detail).toMatch(/h1 to h3/)
  })

  it('reports EVERY gap, not just the first', () => {
    // The backend detector used to break after the first; the fix closes them all in one
    // pass, so reporting one understated the work. Parity matters — same page, same count.
    const findings = r246.check(parse('<h1>One</h1><h3>Three</h3><h1>Two</h1><h4>Four</h4>'))
    expect(findings).toHaveLength(2)
    expect(new Set(findings.map((f) => f.detail)).size).toBe(2) // ordinal keeps them distinct
  })

  it('treats h1→h3→h4 as ONE gap — the h3→h4 step is well-formed', () => {
    expect(r246.check(parse('<h1>One</h1><h3>Three</h3><h4>Four</h4>'))).toHaveLength(1)
  })

  it('ignores a well-formed outline', () => {
    expect(r246.check(parse('<h1>One</h1><h2>Two</h2><h3>Three</h3>'))).toEqual([])
  })

  it('never judges the first heading, so a page starting at h3 scans clean', () => {
    // Matches scanner.py's `prev_level > 0` guard. This is exactly why a clean 2.4.6 result
    // is REVIEW and not a certified pass (ADR 0023 audit, Correction 2).
    expect(r246.check(parse('<h3>Deep</h3><h4>Deeper</h4>'))).toEqual([])
  })

  it('fix clamps every gap and re-checks clean, preserving text and attributes', () => {
    const doc = parse('<h1>One</h1><h3 id="x">Three</h3><h1>Two</h1><h4>Four</h4>')
    const changes = r246.fix(doc)
    expect(changes.size).toBeGreaterThan(0)
    expect(r246.check(doc)).toEqual([])
    expect(doc.querySelector('h2#x')).not.toBeNull()
    expect(doc.body.textContent).toContain('Three')
  })

  it('stays fixMode auto — deterministic to fix, even though a clean scan is not a pass', () => {
    // The two axes are independent: remediation auto, assessment review (capability.js).
    expect(r246.meta.fixMode).toBe('auto')
    const cap = readFileSync(repoFile('frontend/src/capability.js'), 'utf8')
    const html = /"html":\s*\{([\s\S]*?)\}/.exec(cap.slice(cap.indexOf('ASSESSMENT_FALLBACK')))
    expect(html[1]).toMatch(/"2\.4\.6":\s*"review"/)
  })
})

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import AssertionScope from './AssertionScope.jsx'

// "Scope of this assertion" — what the Overview's numbers are a claim ABOUT.
//
// The Overview exports as the compliance report. A report that states findings without stating its
// own boundary is the document this panel exists to prevent, so the cases that matter most here
// are the ABSENT ones: a row an auditor reads as blank is a row they will fill in with the
// generous assumption.

const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'AssertionScope.jsx'), 'utf8')

const CORE = new Set(['1.1.1', '1.3.1', '1.3.2', '1.4.3', '2.4.2', '2.4.6', '3.1.1'])

const SCOPED_RUN = {
  id: 's1', source: 'drive',
  scope: { kind: 'drive', raw: 12408, kept: 12408 },
  scan_scope: { '1.1.1': ['docx', 'pdf'], '1.3.1': ['docx', 'pdf'], '1.4.3': ['docx', 'pdf', 'pptx'] },
}

const REC = {
  discovered: 12408, overridden: 9,
  rows: [
    { key: 'assessed', measured: true, value: 7946 },
    { key: 'lifecycle', measured: true, value: 343 },
  ],
}

const render = (props = {}) =>
  renderToStaticMarkup(createElement(AssertionScope, {
    run: SCOPED_RUN, fileCount: 12408, coreScs: CORE, rec: REC, ...props,
  })).replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&')
     .replace(/&quot;/g, '"').replace(/&#x2F;/g, '/').replace(/\s+/g, ' ')

describe('the assertion boundary is stated, not assumed', () => {
  it('names the document types the run was scoped to', () => {
    expect(render()).toMatch(/DOCX, PDF, PPTX/)
  })

  it('names the criteria count against the core it is a subset of', () => {
    expect(render()).toMatch(/3 of the Core 7/)
  })

  it('states the conformance level as DERIVED, not chosen', () => {
    // The picker was removed on Deva's instruction: there is no correlation wired between a level
    // selector and the criterion selection, so the criteria drive it. Saying "derived" on screen is
    // what stops a reader treating it as a knob they forgot to set.
    const t = render()
    expect(t).toMatch(/WCAG 2\.1 AA/)
    expect(t).toMatch(/derived from the criteria selected/)
  })

  it('says UNRESTRICTED plainly when the scope is null, rather than listing nothing', () => {
    // null scan_scope means the whole document core — the opposite of an empty scope, and the
    // reassuring lie every scope module here refuses to tell.
    const t = render({ run: { ...SCOPED_RUN, scan_scope: null } })
    expect(t).toMatch(/All supported document types/)
    expect(t).toMatch(/not narrowed by type/)
    // and the criteria row reports the whole core, not zero
    expect(t).toMatch(/7 of the Core 7/)
  })

  it('reports what was held back, and that holding back is not deletion', () => {
    const t = render()
    expect(t).toMatch(/343 files held back by a lifecycle recommendation/)
    expect(t).toMatch(/9 individually overridden and assessed/)
    expect(t).toMatch(/Nothing was archived, moved or deleted/)
  })

  it('omits the exclusion row entirely when the bucket was never measured', () => {
    // "0 excluded" from an unmeasured bucket is the same false reassurance as a score over an
    // unassessed estate.
    const t = render({ rec: { discovered: 12408, overridden: null, rows: [{ key: 'lifecycle', measured: false, value: null }] } })
    expect(t).not.toMatch(/held back/)
    expect(t).not.toMatch(/Exclusion policy/)
  })

  it('omits the exclusion row when there is no reconciliation at all', () => {
    expect(render({ rec: null })).not.toMatch(/Exclusion policy/)
  })
})

describe('what it refuses to claim', () => {
  it('never attributes an approval the run does not carry', () => {
    // The discovery acknowledgement is not projected onto the run, so there is no approver to
    // print. A blank "Approved by" reads as "nobody approved"; the signed-in user's name would
    // attribute an approval they may not have given. The row is absent instead.
    expect(render()).not.toMatch(/Approved by/)
  })

  it('renders the approval row only when the run actually carries one', () => {
    // Guards the case above from passing vacuously — if the row could never render, its absence
    // would prove nothing.
    const t = render({ run: { ...SCOPED_RUN, approved_by: 'auditor@example.com', approved_at: 'Aug 20, 2026' } })
    expect(t).toMatch(/Approved by auditor@example\.com · Aug 20, 2026/)
  })

  it('carries no score, and no sentence shaped like one', () => {
    const t = render()
    // Board 7's footer read "A score of 100 would mean no blocking findings among the criteria
    // evaluated". #545 removed the score; the caveat makes the same point without resurrecting it.
    expect(t).not.toMatch(/score/i)
    expect(t).not.toMatch(/\b\d{1,3}\s*\/\s*100\b/)
    expect(t).not.toMatch(/\b\d{1,3}%/)
    expect(t).toMatch(/not the same as conformance/)
  })

  it('reads the frozen run scope, never the live setting', () => {
    // An operator who widens the global scope after a run must still see what THIS run covered.
    expect(src).toMatch(/run\.scan_scope/)
    expect(src).not.toMatch(/\bSCOPE_SCS\b/)
  })

  it('renders nothing at all without a run', () => {
    expect(renderToStaticMarkup(createElement(AssertionScope, { run: null }))).toBe('')
  })
})

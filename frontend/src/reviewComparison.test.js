// The current→remediated block a reviewer approves against. Rendered for real (react-dom's
// static renderer — no testing-library in this repo) so the assertions are about output, not
// about the source text that produces it.
import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { ReviewComparison } from './Remediate.jsx'

const render = (comparison) => renderToStaticMarkup(createElement(ReviewComparison, { comparison }))

describe('ReviewComparison — an applied fix versus a draft awaiting approval', () => {
  it('an applied remediation_diff says the document already carries the fix', () => {
    const html = render({ before: '(no alt text)', after: 'A clinician at a desk.', applied: true })
    expect(html).toMatch(/applied to the document/)
    expect(html).toMatch(/\(no alt text\)/)
    expect(html).toMatch(/A clinician at a desk\./)
    // It must NOT tell the reviewer their approval is what applies it — it is already applied.
    expect(html).not.toMatch(/not applied until you approve/)
  })

  it('a proposal is labelled a draft that approval will apply — never as already done', () => {
    const html = render({ before: '(no alt text)', after: 'A parent signing a form.', applied: false })
    expect(html).toMatch(/AI draft/)
    expect(html).toMatch(/not applied until you approve/)
    expect(html).not.toMatch(/applied to the document/)
  })

  it('an absent "before" reads as absent, not as an empty box', () => {
    const html = render({ before: null, after: 'Some alt text.', applied: false })
    expect(html).toMatch(/nothing \(the value is absent\)/)
  })

  it('renders the two halves with the shared diffbox styling', () => {
    const html = render({ before: 'a', after: 'b', applied: true })
    expect(html).toMatch(/class="diffbox before"/)
    expect(html).toMatch(/class="diffbox after"/)
    expect((html.match(/difftag/g) || []).length).toBe(2)
  })

  it('never emits the canned claims the card used to print', () => {
    const html = render({ before: 'x', after: 'y', applied: true })
    expect(html).not.toMatch(/AI-generated alt text added|AI fix applied/)
  })
})

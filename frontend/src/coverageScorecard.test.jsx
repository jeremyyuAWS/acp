import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// Unmount every root this file mounts — see testRoots.js.
afterEach(unmountAll)

const { default: CoverageScorecard } = await import('./CoverageScorecard.jsx')

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })

const render = async (files) => { await act(async () => { root.render(createElement(CoverageScorecard, { files })) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const btnByText = (t) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))

describe('CoverageScorecard renders the two-axis capability view (ADR 0023)', () => {
  it('an all-.xlsx estate shows both layers + customer-outcome lanes, scoped to .xlsx', async () => {
    await render([{ file: 'book.xlsx', type: 'xlsx' }])
    const txt = container.textContent
    expect(txt).toContain('what we can assess')
    expect(txt).toContain('.xlsx')                       // scoped to the estate's file type
    // Assessment layer, customer-outcome wording (not "deterministic/OCR/vision").
    expect(txt).toContain('Assessment')
    expect(txt).toContain('Fully Assessed')
    expect(txt).toContain('Potential Issue')
    // Remediation layer is a distinct row.
    expect(txt).toContain('Remediation')
    expect(txt).toContain('AI Generated Fix')
    // xlsx: 5 🟢 auto-assessable + 10 🟡 review (Use of Color, Non-text Contrast and
    // Name/Role/Value are all registry-backed review lanes now — see R8).
    expect(txt).toContain('5')
    expect(txt).toContain('10')
    // No implementation jargon leaked into the customer view.
    expect(txt).not.toContain('deterministic remediation')
  })

  it('expands an .html estate grouped by assessment lane, showing needs-AT keyboard criteria', async () => {
    await render([{ file: 'page.html', type: 'html' }])
    await click(btnByText('Show all'))
    const txt = container.textContent
    expect(txt).toContain('1.4.3')                       // a 🟢 auto criterion
    expect(txt).toContain('2.1.1')                       // a keyboard criterion
    expect(txt).toContain('needs AT testing')             // folded into the 🔴 human-only lane
  })

  it('office estate shows 🟡 review lane for the control-gated criteria (2.1.2 / 4.1.2)', async () => {
    await render([{ file: 'a.docx', type: 'docx' }])
    await click(btnByText('Show all'))
    const txt = container.textContent
    expect(txt).toContain('Potential Issue')
    expect(txt).toContain('2.1.2')
    expect(txt).toContain('4.1.2')
  })

  // The scorecard and the WCAG capability matrix are two renderings of one judgement, so they
  // have to use one vocabulary — docs/acp-architecture-deck.md fixes it as A4/A3/A2/NA and
  // R4/R3/R2. Pinning the strings is the point: a rename that only lands on one surface is the
  // failure this guards, and it is invisible in a diff of either file alone. The old wording is
  // asserted absent too, because a half-finished rename leaves both spellings on the page.
  it('every lane label on the page is the matrix vocabulary, on both axes', async () => {
    await render([{ file: 'a.docx', type: 'docx' }])
    await click(btnByText('Rule × format grid'))
    const txt = container.textContent
    for (const label of ['Fully Assessed', 'Potential Issue', 'Human Assessment Required',
                         'Automatically Fixed', 'AI Generated Fix', 'Guided']) {
      expect(txt).toContain(label)
    }
    for (const stale of ['Auto assessment', 'Review recommended', 'Human-only', 'AI-assisted']) {
      expect(txt).not.toContain(stale)
    }
  })

  it('the Rule × format grid shows every criterion across the four document types', async () => {
    await render([{ file: 'a.docx', type: 'docx' }])
    await click(btnByText('Rule × format grid'))
    const txt = container.textContent
    // column headers for the four document formats
    for (const f of ['.docx', '.xlsx', '.pptx', '.pdf']) expect(txt).toContain(f)
    // a representative criterion row + a lane emoji legend
    expect(txt).toContain('1.4.3')
    expect(txt).toContain('🟢')
    expect(txt).toContain('🟡')
    // grid cells render the assessment-lane emoji (🟢 for 1.4.3 contrast in every format)
    const cells = [...container.querySelectorAll('td')].filter((td) => td.textContent.trim() === '🟢')
    expect(cells.length).toBeGreaterThan(0)
  })

  it('toggling to all-document criteria grows the total beyond 20', async () => {
    await render([{ file: 'a.docx', type: 'docx' }])
    expect(container.textContent).toContain('20-check document core')
    await click(btnByText('20-check document core'))      // switch off documents → all document criteria
    expect(/\/(2[1-9]|[3-9]\d)/.test(container.textContent)).toBe(true)
  })

  // Three totals for "how many criteria apply" are visible across the product — the criteria
  // traced per format (~38), the 20-check document core, and the 14 in the engagement's agreed
  // scope. They answer three different questions, so they are not reconciled by making them
  // equal; they are reconciled by each surface SAYING which one it is counting. This panel's is
  // the widest of the three, and it sits directly above the panel that uses the narrowest, which
  // is the adjacency that made an unlabelled 20 beside a 14 read as a contradiction.
  it('names its own denominator and the narrower one the panel below uses', async () => {
    await render([{ file: 'a.docx', type: 'docx' }])
    const txt = container.textContent
    expect(txt).toContain('20-check document core')
    expect(txt).toContain('what ACP can assess for these file types')
    expect(txt).toContain('14 criteria in your agreed scope')
    expect(txt).toContain('not meant to match')
    expect(txt).not.toMatch(/Deva/)                       // customer name never reaches the UI
  })

  // Coverage-gap warning (assessmentGaps). Folding gap→⚪ and at→🔴 hid whether a cell was a
  // genuine "no method" hole; this states it per format, honestly, in both directions.
  it('a document-only estate states there are NO coverage gaps rather than staying silent', async () => {
    await render([{ file: 'a.docx', type: 'docx' }])
    const txt = container.textContent
    expect(txt).toContain('No coverage gaps')
    expect(txt).not.toContain('no assessment method for')   // no per-format warning when there are none
  })

  it('an .html estate warns that 2.1.1 / 2.1.2 have no assessment method (needs AT)', async () => {
    await render([{ file: 'page.html', type: 'html' }])
    const txt = container.textContent
    expect(txt).toContain('Coverage gaps')
    expect(txt).toContain('no assessment method for')
    expect(txt).toContain('.html')
    expect(txt).toContain('2.1.1')
    expect(txt).toContain('2.1.2')
    expect(txt).toContain('2 criteria have')               // the plain-language rollup
    expect(txt).not.toContain('No coverage gaps')          // the positive message is suppressed when gaps exist
  })
})

import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

// The preview pane's adaptive VIEW MODES: Visual · Properties (· Structure for a structure finding).
// Run WITHOUT a scanId on purpose — that path is fully deterministic (no API, no blob URL), so these
// pin the mode switcher and the Properties/Structure surfaces built purely from the finding prop.
const { default: RemediationPreview } = await import('./RemediationPreview.jsx')

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })
const render = async (props) => { await act(async () => { root.render(createElement(RemediationPreview, props)) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const tab = (label) => [...container.querySelectorAll('[role=tab]')].find((b) => b.textContent.trim() === label)
const tabLabels = () => [...container.querySelectorAll('[role=tab]')].map((b) => b.textContent.trim())

// A visible-region finding (has a page → a visual anchor), carrying the metadata the Properties
// panel reads. rule_id arrives prefixed ("WCAG_1.4.3") to exercise the display normalisation.
const VISUAL = {
  id: 1, file: 'brief.docx', page: 3,
  rule_id: 'WCAG_1.4.3', severity: 'CRITICAL', source: 'Google Drive',
  before: '#D9D9D9 on #FFFFFF', after: 'Darken text to #595959',
}
// A structure/metadata finding: missing document title — no page/locator/thumb, so no visual anchor.
const STRUCTURAL = { id: 2, file: 'annual-report.docx', rule_id: '2.4.2', severity: 'SERIOUS', after: 'Annual Report 2026' }

describe('RemediationPreview — adaptive view modes', () => {
  it('renders the Visual · Properties mode switcher for a visible finding (no Structure mode)', async () => {
    await render({ finding: VISUAL })
    expect(tab('Visual')).toBeTruthy()
    expect(tab('Properties')).toBeTruthy()
    // Structure is not offered for a finding that HAS a visual anchor — the mode list stays honest.
    expect(tab('Structure')).toBeFalsy()
    // Visual is the default mode, so the Before/After/Side-by-side toggle is present.
    expect(tab('Before')).toBeTruthy()
    expect(tab('Side by side')).toBeTruthy()
  })

  it('Visual mode keeps the existing before/after behaviour intact', async () => {
    await render({ finding: VISUAL })            // default: Visual + Before
    expect(container.textContent).toContain('#D9D9D9 on #FFFFFF')       // the original value
    await click(tab('After'))
    expect(container.textContent).toContain('Darken text to #595959')   // the proposed value
    expect(container.textContent).toContain('re-validated by a fresh scan')
  })

  it('Properties mode surfaces the finding’s file, format, WCAG code, severity and source', async () => {
    await render({ finding: VISUAL })
    await click(tab('Properties'))
    // The Before/After view toggle is not meaningful outside Visual mode, so it is gone.
    expect(tab('Before')).toBeFalsy()
    expect(container.textContent).toContain('brief.docx')     // file
    expect(container.textContent).toContain('DOCX')           // format
    expect(container.textContent).toContain('WCAG 1.4.3')     // normalised WCAG code
    expect(container.textContent).toContain('CRITICAL')       // severity
    expect(container.textContent).toContain('Google Drive')   // source
    expect(container.textContent).toContain('#D9D9D9 on #FFFFFF')   // current value
    expect(container.textContent).toContain('Darken text to #595959') // proposed value
    // Honest provenance line: everything came from the finding, nothing fetched.
    expect(container.textContent).toContain('nothing here is fetched or inferred')
  })

  it('switching modes back and forth works', async () => {
    await render({ finding: VISUAL })
    await click(tab('Properties'))
    expect(container.textContent).toContain('Google Drive')
    await click(tab('Visual'))
    expect(container.textContent).toContain('#D9D9D9 on #FFFFFF')   // back to the Visual/Before surface
    expect(container.textContent).not.toContain('nothing here is fetched or inferred')
  })

  it('offers a Structure mode for a structure/metadata finding with an HONEST, non-fabricated note', async () => {
    await render({ finding: STRUCTURAL })
    expect(tab('Structure')).toBeTruthy()
    await click(tab('Structure'))
    // Names the criterion and states plainly that structure is computed during assessment, not drawn.
    expect(container.textContent).toContain('document-structure finding')
    expect(container.textContent).toContain('WCAG 2.4.2')
    expect(container.textContent).toContain('computed during assessment')
    expect(container.textContent).toContain('not yet extracted for preview')
    // Honesty: no fabricated tag tree / reading-order artefact is rendered.
    expect(container.textContent).not.toContain('reading order:')
    expect(container.querySelector('ol')).toBeNull()
    expect(container.querySelector('ul')).toBeNull()
  })

  it('Structure finding still exposes its metadata honestly in Properties', async () => {
    await render({ finding: STRUCTURAL })
    await click(tab('Properties'))
    expect(container.textContent).toContain('annual-report.docx')
    expect(container.textContent).toContain('WCAG 2.4.2')
    expect(container.textContent).toContain('SERIOUS')
    // Location was not attributed for this finding — stated as unavailable (—), not invented.
    // (The label is upper-cased by CSS only, so the DOM text is "Location".)
    expect(container.textContent).toContain('Location')
    expect(container.textContent).toContain('—')
  })
})

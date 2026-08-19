import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

// The third pane. Tests run WITHOUT a scanId on purpose — that path is fully deterministic (no API,
// no blob/URL.createObjectURL), and it is also the exact state the inbox test renders the pane in,
// so this pins the null-safe behaviour that keeps RemediationInbox.test.jsx green.
const { default: RemediationPreview } = await import('./RemediationPreview.jsx')

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })
const render = async (props) => { await act(async () => { root.render(createElement(RemediationPreview, props)) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const tab = (label) => [...container.querySelectorAll('[role=tab]')].find((b) => b.textContent.trim() === label)

// A visible-region finding (has a page → a visual anchor) vs. a structure finding (title/metadata).
const VISUAL = { id: 1, file: 'brief.docx', page: 3, before: '#D9D9D9 on #FFFFFF', after: 'Darken text to #595959' }
const STRUCTURAL = { id: 2, file: 'annual-report.docx', after: 'Annual Report 2026' } // missing title: no page/locator/thumb

describe('RemediationPreview — contextual document pane', () => {
  it('shows an empty state when no finding is selected', async () => {
    await render({ finding: null })
    expect(container.textContent).toContain('Select a finding to see it in the document')
  })

  it('headers the pane with the file, format and location', async () => {
    await render({ finding: VISUAL })
    expect(container.textContent).toContain('brief.docx')
    expect(container.textContent).toContain('DOCX')
    expect(container.textContent).toContain('Page 3')
  })

  it('is adaptive: a structure/metadata finding is NOT faked onto the rendered page', async () => {
    await render({ finding: STRUCTURAL })
    expect(container.textContent).toContain('structure or metadata')
    expect(container.textContent).not.toContain('live page preview')
  })

  it('a visible finding with no scan shows the "before" and a connect-a-scan note, not a broken image', async () => {
    await render({ finding: VISUAL })            // default view = before
    expect(container.textContent).toContain('#D9D9D9 on #FFFFFF')       // the original value
    expect(container.textContent).toContain('live page preview appears here')
    expect(container.querySelector('img')).toBeNull()                   // no scanId → no image element
  })

  it('renders the real "before" value, never the beforeLiteral boolean flag', async () => {
    // Regression: Remediate.jsx sets `beforeLiteral: !!firstBefore(it)` (a boolean). The pane used
    // to read `beforeLiteral ?? before`, so it rendered the FLAG — "before false" when absent,
    // "before true" when present — instead of the value. It must show `f.before`.
    await render({ finding: { id: 9, file: 'brief.docx', page: 3, beforeLiteral: false, before: 'Required property not present', after: 'Add the property' } })
    expect(container.textContent).toContain('Required property not present')
    expect(container.textContent).not.toContain('before false')
    expect(container.textContent).not.toContain('before true')
  })

  it('the After view shows the proposed change and that it re-validates on approval', async () => {
    await render({ finding: VISUAL })
    await click(tab('After'))
    expect(container.textContent).toContain('Darken text to #595959')
    expect(container.textContent).toContain('re-validated by a fresh scan')
  })

  it('embedded mode is the document view only — no duplicate file header, no repeated value diff', async () => {
    // Folded into the workspace Evidence section: the workspace already names the file and shows the
    // before/after value in "How to fix", so embedded Visual shows the page/structure view only.
    await render({ finding: VISUAL, embedded: true })
    expect(tab('Visual')).toBeTruthy()                         // mode tabs still offered
    expect(tab('Properties')).toBeTruthy()
    expect(tab('After')).toBeFalsy()                           // no Before/After value tabs here
    expect(container.textContent).not.toContain('#D9D9D9 on #FFFFFF')  // the value diff isn't repeated
    expect(container.textContent).not.toContain('Select a finding')    // the empty note is the workspace's job
  })

  it('embedded structure finding folds to the honest structure note, not an empty frame', async () => {
    await render({ finding: STRUCTURAL, embedded: true })
    expect(container.textContent).toContain('structure')
  })

  it('Side by side shows the found and proposed states together', async () => {
    await render({ finding: VISUAL })
    await click(tab('Side by side'))
    expect(container.textContent).toContain('Found')
    expect(container.textContent).toContain('Proposed')
    expect(container.textContent).toContain('#D9D9D9 on #FFFFFF')       // found
    expect(container.textContent).toContain('Darken text to #595959')  // proposed
  })

  // ── Zoom (mockup "− 100% +") — UI-only, no data required ──────────────────────────────────────
  const zoomBtn = (label) => [...container.querySelectorAll('button')].find((b) => (b.getAttribute('aria-label') || '') === label)

  it('offers a UI-only zoom control in Visual mode that steps the percentage', async () => {
    await render({ finding: VISUAL })
    expect(container.textContent).toContain('100%')        // starts at 100%
    expect(zoomBtn('Zoom in')).toBeTruthy()
    expect(zoomBtn('Zoom out')).toBeTruthy()
    await click(zoomBtn('Zoom in'))
    expect(container.textContent).toContain('125%')
    await click(zoomBtn('Zoom out'))
    await click(zoomBtn('Zoom out'))
    expect(container.textContent).toContain('75%')
  })

  // ── Fix callouts — grounded ONLY on real applied/verified state (ADR 0016) ─────────────────────
  it('shows NO fix callout for a bare proposal (after present but not applied)', async () => {
    await render({ finding: VISUAL })       // has `after`, but no applied/verified/status
    await click(tab('After'))
    expect(container.querySelector('.fix-callout')).toBeNull()
  })

  it('shows a "✓ <what changed>" callout only once the fix is actually applied', async () => {
    await render({ finding: { ...VISUAL, applied: true } })
    await click(tab('After'))
    const callout = container.querySelector('.fix-callout')
    expect(callout).toBeTruthy()
    expect(callout.textContent).toContain('Darken text to #595959')  // the real applied after-value
    expect(container.textContent).not.toContain('Re-scan cleared')   // not verified yet
  })

  it('adds "Re-scan cleared" only for a verified finding, never fabricated', async () => {
    await render({ finding: { ...VISUAL, status: 'verified' } })
    await click(tab('After'))
    expect(container.textContent).toContain('Re-scan cleared')
  })
})

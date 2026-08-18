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

  it('the After view shows the proposed change and that it re-validates on approval', async () => {
    await render({ finding: VISUAL })
    await click(tab('After'))
    expect(container.textContent).toContain('Darken text to #595959')
    expect(container.textContent).toContain('re-validated by a fresh scan')
  })

  it('Side by side shows the found and proposed states together', async () => {
    await render({ finding: VISUAL })
    await click(tab('Side by side'))
    expect(container.textContent).toContain('Found')
    expect(container.textContent).toContain('Proposed')
    expect(container.textContent).toContain('#D9D9D9 on #FFFFFF')       // found
    expect(container.textContent).toContain('Darken text to #595959')  // proposed
  })
})

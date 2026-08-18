/**
 * Discover shows the whole discovered estate, and a Document Location control filters the VIEW
 * (Discover/Assess PRD §4.1).
 *
 * Two changes are pinned here. (1) The file-type gate is gone — Discover no longer narrows its list
 * by document type (that decision moved to Assess), so a fileTypeConfig that would once have hidden
 * a type has no effect. (2) A Document Location filter narrows what is shown by source drive /
 * folder / path, WITHOUT restricting discovery: the estate count beside it stays whole.
 *
 * DOM-level, not browser-level: the preview server runs vite rooted at the SHARED checkout whatever
 * worktree you are in, so a browser check of a worktree change exercises code that does not contain
 * it (CLAUDE.md).
 */
import { describe, it, expect, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const { default: Discover } = await import('./Discover.jsx')

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })
afterEach(unmountAll)

const FILE = (name, extra = {}) => ({
  file: name, type: name.split('.').pop().toUpperCase(), tags: [], issues: [],
  department: 'Legal', sourceName: 'Google Drive', ...extra,
})

const render = async (props) => {
  await act(async () => {
    root.render(createElement(Discover, {
      sources: [{ name: 'Google Drive' }, { name: 'SharePoint' }],
      files: [FILE('a.docx')], busy: false, onScan: () => {}, hasDriveToken: true, ...props,
    }))
  })
}

const type = async (el, v) => {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  await act(async () => { setter.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true })) })
}
const selectValue = async (el, v) => {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set
  await act(async () => { setter.call(el, v); el.dispatchEvent(new Event('change', { bubbles: true })) })
}
const locCount = () => container.querySelector('.doclocbar-count')?.textContent || ''

const MIXED = [
  FILE('HR/policies/leave.docx', { sourceName: 'Google Drive', department: 'Human Resources' }),
  FILE('Legal/contracts/nda.pdf', { sourceName: 'Google Drive', department: 'Legal' }),
  FILE('deck.pptx', { sourceName: 'SharePoint', department: 'Communications' }),
]


describe('Discover no longer gates by document type', () => {
  it('shows every type even when a fileTypeConfig would exclude one', async () => {
    // fileTypeConfig is no longer a Discover prop; passing one must have no effect on what shows.
    await render({ files: [FILE('a.docx'), FILE('b.pdf'), FILE('c.pptx')], fileTypeConfig: { pdf: false } })
    const legend = container.querySelector('.typelegend')?.textContent || ''
    expect(legend, 'pdf was gated out of the type legend').toContain('PDF')
    expect(legend).toContain('DOCX')
    expect(legend).toContain('PPTX')
    // and no "excluded by file-type settings" caveat survives
    expect(container.textContent).not.toMatch(/excluded by file-type settings/i)
  })
})


describe('the Document Location filter narrows the shown list', () => {
  it('filters by a folder/path substring', async () => {
    await render({ files: MIXED })
    const input = container.querySelector('input[aria-label="Filter by folder or path"]')
    expect(input, 'no path filter input').toBeTruthy()
    await type(input, 'Legal')
    expect(locCount()).toMatch(/1 of 3 shown/)
  })

  it('filters by source drive', async () => {
    await render({ files: MIXED })
    const select = container.querySelector('select[aria-label="Filter by source"]')
    expect(select, 'no source selector').toBeTruthy()
    await selectValue(select, 'SharePoint')
    expect(locCount()).toMatch(/1 of 3 shown/)
  })

  it('is a view filter only — the discovered estate count stays whole', async () => {
    await render({ files: MIXED })
    const input = container.querySelector('input[aria-label="Filter by folder or path"]')
    await type(input, 'Legal')
    // the estate bar still reports all three discovered — the filter did not restrict discovery
    expect(container.textContent).toContain('3 documents')
    expect(locCount()).toMatch(/2 hidden by location/)
  })
})

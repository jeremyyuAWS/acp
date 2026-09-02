/**
 * Discover shows the whole discovered estate, and a Document Location control filters the VIEW
 * (Discover/Assess PRD §4.1).
 *
 * Two changes were pinned here. (1) The file-type gate is gone — Discover no longer narrows its
 * list by document type (that decision moved to Assess), so a fileTypeConfig that would once have
 * hidden a type has no effect. That is unchanged, and is asserted below against the BY FILE TYPE
 * breakdown, which is where every discovered type is now listed.
 *
 * (2) The Document Location filter — filter-by-source-drive / folder / path, narrowing the VIEW
 * without restricting discovery — was REMOVED on 2026-09-02 with the per-department block it lived
 * in (PRD "ACP Discover and Overview Simplification"). That is a capability this screen no longer
 * offers, not a control that moved: nothing else on Discover filters the list by location. It is
 * pinned as removed here so its absence is a recorded decision rather than an unnoticed
 * regression, and so a restored filter has to restore the view-only guarantee with it.
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

const MIXED = [
  FILE('HR/policies/leave.docx', { sourceName: 'Google Drive', department: 'Human Resources' }),
  FILE('Legal/contracts/nda.pdf', { sourceName: 'Google Drive', department: 'Legal' }),
  FILE('deck.pptx', { sourceName: 'SharePoint', department: 'Communications' }),
]


describe('Discover no longer gates by document type', () => {
  it('shows every type even when a fileTypeConfig would exclude one', async () => {
    // fileTypeConfig is no longer a Discover prop; passing one must have no effect on what shows.
    await render({ files: [FILE('a.docx'), FILE('b.pdf'), FILE('c.pptx')], fileTypeConfig: { pdf: false },
                   run: { id: 's1', status: 'discovered', discovered_at: '2026-09-01T00:00:00Z' },
                   scope: { kind: 'drive', inventory: { discovered: 3 } }, scanId: 's1' })
    const text = container.textContent
    expect(text, 'the type breakdown did not render at all').toContain('BY FILE TYPE')
    expect(text, 'pdf was gated out of the type breakdown').toContain('PDF')
    expect(text).toContain('DOCX')
    expect(text).toContain('PPTX')
    // and no "excluded by file-type settings" caveat survives
    expect(text).not.toMatch(/excluded by file-type settings/i)
  })
})


describe('the Document Location filter is gone from Discover', () => {
  const mounted = async () => {
    await render({ files: MIXED,
                   run: { id: 's1', status: 'discovered', discovered_at: '2026-09-01T00:00:00Z' },
                   scope: { kind: 'drive', inventory: { discovered: 3 } }, scanId: 's1' })
    // The list itself IS on screen — otherwise the three absences below say nothing about the
    // filter and everything about a failed mount.
    expect(container.textContent).toContain('BY FILE TYPE')
  }

  it('offers no folder/path filter input', async () => {
    await mounted()
    expect(container.querySelector('input[aria-label="Filter by folder or path"]')).toBeNull()
  })

  it('offers no source-drive selector', async () => {
    await mounted()
    expect(container.querySelector('select[aria-label="Filter by source"]')).toBeNull()
  })

  it('shows the whole discovered estate, with no "N hidden by location" count to show', async () => {
    await mounted()
    expect(container.querySelector('.doclocbar-count')).toBeNull()
    expect(container.textContent).not.toMatch(/hidden by location/)
    // Every discovered document is still counted — the filter never restricted discovery, and
    // removing it must not have started restricting it either.
    expect(container.textContent).toMatch(/discovered3/)
  })
})

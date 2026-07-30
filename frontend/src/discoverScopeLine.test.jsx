// Discover actually RENDERS the boundary beside the count.
//
// scanScope.test.js pins the sentence; this pins the wiring — App passes `run.scope` down, and
// the estate bar puts it on screen. A correct sentence nobody renders is the same defect with a
// unit test in front of it, which is exactly the shape the 2026-07-30 report took: the counts
// were computed correctly all along and only reached stdout.
import { describe, it, expect, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const { default: Discover } = await import('./Discover.jsx')

let container, root
beforeEach(() => {
  ;({ container, root } = createTestRoot())
})

// Unmount, rather than leaving the tree standing for the environment teardown to race — the same
// exposure #103 fixed in inventoryAgreesWithDrawer/drawerFindingsClaim, which this file has too.
// It is no longer only latent: on a clean checkout this suite exited non-zero on 1 of 4 full runs,
// every test reporting passed, with `ReferenceError: window is not defined` thrown out of
// getActiveElementDeep after the last assertion. That is a CI job that reddens at random and gets
// re-run instead of fixed.
afterEach(unmountAll)

const FOLDER_SCOPE = { kind: 'folder', folder_id: '1W27ULZ', folder_name: 'WCAG Defense Pack',
                       folders_walked: 1, listed: 1, kept: 1, truncated: false }
const DRIVE_SCOPE = { kind: 'drive', raw: 11, scannable: 8, kept: 8, truncated: false }

const FILE = (name) => ({ file: name, type: name.split('.').pop().toUpperCase(), tags: [], issues: [] })

const render = async (props) => {
  await act(async () => {
    root.render(createElement(Discover, {
      sources: [{ name: 'Google Drive' }], files: [FILE('a.docx')], busy: false,
      onScan: () => {}, hasDriveToken: true, ...props,
    }))
  })
}

describe('the estate bar states what the count counted', () => {
  it('a one-folder scan says so, and names the folder', async () => {
    await render({ scope: FOLDER_SCOPE })
    const txt = container.textContent
    expect(txt).toContain('WCAG Defense Pack')
    expect(txt).toMatch(/not scanned/)
  })

  it('offers the way out of a folder-scoped scan', async () => {
    // The user's next question is "then how do I see everything?", so the answer is a button.
    await render({ scope: FOLDER_SCOPE })
    const btn = [...container.querySelectorAll('button')]
      .find((b) => /whole Drive/i.test(b.textContent))
    expect(btn).toBeTruthy()
  })

  it('a whole-Drive scan says that instead, without a warning', async () => {
    await render({ scope: DRIVE_SCOPE, files: [FILE('a.docx')] })
    expect(container.textContent).toContain('across your whole Google Drive')
    expect(container.querySelector('.scopewarn')).toBeNull()
  })

  it('marks the narrow case up as a status so it is not read as decoration', async () => {
    await render({ scope: FOLDER_SCOPE })
    const warn = container.querySelector('.scopewarn')
    expect(warn).toBeTruthy()
    expect(warn.getAttribute('role')).toBe('status')
  })

  it('says nothing at all when no scope was recorded', async () => {
    // Every pre-existing production scan. Silence, not a reassuring guess.
    await render({ scope: null })
    const txt = container.textContent
    expect(txt).not.toContain('whole Google Drive')
    expect(txt).not.toContain('not scanned')
    expect(container.querySelector('.scopewarn')).toBeNull()
  })

  it('states the number the user can see, not the number discovery listed', async () => {
    // kept=1 in the scope, but two rows survive to the screen: the sentence sits beside the
    // rendered list and has to be about it.
    await render({ scope: { ...FOLDER_SCOPE, kept: 1 }, files: [FILE('a.docx'), FILE('b.pdf')] })
    expect(container.textContent).toContain('2 documents in the Drive folder')
  })

  it('reports a truncated listing as files it could not see', async () => {
    await render({ scope: { kind: 'drive', kept: 500, truncated: true, cap: 2500 } })
    expect(container.textContent).toMatch(/did not see/)
    expect(container.querySelector('.scopewarn')).toBeTruthy()
  })
})

/**
 * Carving a child out of an included parent, in the UI.
 *
 * PRD §6.3: a selected parent includes every accessible descendant; an unchecked child beneath it
 * becomes an explicit exclusion. Full tri-state as the PRD describes it ("indeterminate = some
 * descendants selected") needs the whole tree, and the tree loads lazily — but the BREADCRUMB is
 * the ancestry, and a child can only be carved out while you are drilled into it. So the picker
 * derives inheritance from the stack, which is exact rather than approximate.
 *
 * What each case is here to stop, all of which look fine on screen:
 *
 *   · a row inside an included parent showing as UNCHECKED — it reads as "not being scanned"
 *     while the server scans it, and the user's fix (ticking it) is a no-op
 *   · unchecking such a row doing nothing — the chip promises a carve-out that never happens
 *   · exclusions rendered on their own screen or not at all — "HR" and "HR except Archive" are
 *     different scopes, and the card is where someone checks what a count covered
 *   · the scope sentence omitting the carve-out — two runs of the same folder then differ in
 *     count with identical boundaries printed, which is the 2026-07-30 defect one level down
 *
 * DOM-level, not browser-level: the preview server is rooted at the SHARED checkout whatever
 * worktree you are in (CLAUDE.md), so a browser check would exercise code without this change.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { scopeSentence, isNarrowScope } from './scanScope.js'

afterEach(unmountAll)

describe('the scope sentence carries the carve-out', () => {
  const withExclusion = {
    kind: 'folder', kept: 40, truncated: false,
    folders: [{ id: 'prog', name: 'Programme' }],
    excluded: ['arch'],
  }

  it('says folders were excluded', () => {
    expect(scopeSentence(withExclusion, 40)).toContain('excluded')
  })

  it('is still narrow', () => {
    expect(isNarrowScope(withExclusion)).toBe(true)
  })

  it('says nothing about exclusions when there are none', () => {
    // A caveat that fires on every scan stops being read — the reason the repo gates the
    // file-type warning on skipped_out_of_scope > 0 rather than on the setting.
    const plain = { kind: 'folder', kept: 40, truncated: false, folder_name: 'Programme' }
    expect(scopeSentence(plain, 40)).not.toContain('excluded')
  })
})

// ── the picker ───────────────────────────────────────────────────────────────────────────────

vi.mock('./api.js', () => ({
  // Root lists one folder; drilling into it lists two children.
  listFolders: vi.fn(async (parent) => (parent === 'root'
    ? { folders: [{ id: 'prog', name: 'Programme' }] }
    : { folders: [{ id: 'arch', name: 'Archive' }, { id: 'live', name: 'Live' }] })),
}))

const { default: FolderPicker } = await import('./FolderPicker.jsx')

async function openPicker(onConfirm, initial = [], initialExclude = []) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(FolderPicker, {
      onConfirm, onClose: () => {}, initial, initialExclude, rootName: 'My Drive',
    }))
  })
  return container
}

const boxes = (c) => [...c.querySelectorAll('input[type="checkbox"]')]
const byLabel = (c, re) => boxes(c).find((b) => re.test(b.getAttribute('aria-label') || ''))

describe('excluding a child of an included parent', () => {
  it('shows children as already included once the parent is picked', async () => {
    const c = await openPicker(() => {}, [{ id: 'prog', name: 'Programme' }])
    // Drill into Programme.
    const drill = [...c.querySelectorAll('button')].find((b) => /Programme/.test(b.textContent))
    await act(async () => { drill.click() })
    expect(c.textContent).toContain('included via parent')
    // The row must not read as unchecked — that would say "not scanned" about a folder the
    // server is scanning, and ticking it would do nothing.
    const arch = byLabel(c, /Archive/)
    expect(arch, 'no checkbox for the child row').toBeTruthy()
    expect(arch.checked).toBe(true)
  })

  it('unchecking a child records an exclusion rather than a no-op', async () => {
    const confirmed = []
    const c = await openPicker((f, e) => confirmed.push([f, e]), [{ id: 'prog', name: 'Programme' }])
    const drill = [...c.querySelectorAll('button')].find((b) => /Programme/.test(b.textContent))
    await act(async () => { drill.click() })
    await act(async () => { byLabel(c, /Archive/).click() })
    expect(c.textContent).toContain('except Archive')

    const save = [...c.querySelectorAll('button')].find((b) => /^Save/.test(b.textContent.trim()))
    await act(async () => { save.click() })
    const [folders, exclude] = confirmed[0]
    expect(folders.map((f) => f.id)).toEqual(['prog'])
    expect(exclude.map((f) => f.id)).toEqual(['arch'])
  })

  it('a top-level row with no included ancestor still toggles inclusion, not exclusion', async () => {
    // The other branch of rowState. If inheritance were assumed, picking a first folder would
    // silently record it as an exclusion and the scan would cover everything.
    const confirmed = []
    const c = await openPicker((f, e) => confirmed.push([f, e]))
    await act(async () => { byLabel(c, /Programme/).click() })
    const save = [...c.querySelectorAll('button')].find((b) => /^Save/.test(b.textContent.trim()))
    await act(async () => { save.click() })
    const [folders, exclude] = confirmed[0]
    expect(folders.map((f) => f.id)).toEqual(['prog'])
    expect(exclude).toEqual([])
  })

  it('"Scan all" clears the carve-outs as well as the inclusions', async () => {
    // An exclusion left behind would re-arm the moment somebody picked a folder containing it —
    // a narrowing nobody chose, from a decision made about a different scope.
    const confirmed = []
    const c = await openPicker((f, e) => confirmed.push([f, e]),
                               [{ id: 'prog', name: 'Programme' }], [{ id: 'arch', name: 'Archive' }])
    const all = [...c.querySelectorAll('button')].find((b) => /Scan all/.test(b.textContent))
    await act(async () => { all.click() })
    expect(confirmed[0]).toEqual([[], []])
  })
})

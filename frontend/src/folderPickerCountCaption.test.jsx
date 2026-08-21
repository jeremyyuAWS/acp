import { describe, it, expect, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import { SIZE_HINT_BASIS, sizeHint } from './folderTree.js'

// What "128 items" MEANS, said on the screen rather than on hover (design board, step 1).
//
// The number decides what gets scanned, and the wrong reading of it — "430 items" as "430
// documents" — is the one a reader arrives at unaided. Graph's childCount counts subfolders too and
// does not recurse; Google Drive returns no count at all. The explanation existed, as a `title`
// attribute, which is no answer on a touch device and not much of one anywhere else.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: FolderPicker } = await import('./FolderPicker.jsx')

const FOLDERS = [
  { id: 'd/a', name: 'Accessibility Program', child_count: 128 },
  { id: 'd/b', name: 'Finance', child_count: 430 },
]
const NO_COUNTS = [{ id: 'd/a', name: 'HR' }, { id: 'd/b', name: 'Legal' }]

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(FolderPicker, props)) })
  // The picker lists asynchronously; flush the resolved lister before reading.
  await act(async () => { await Promise.resolve() })
  return container.textContent
}
afterEach(() => unmountAll())

const base = (folders) => ({
  layout: 'inline',
  multi: true,
  lister: async () => ({ folders }),
  onChange: () => {},
  selected: [],
})

describe('the item-count caption', () => {
  it('states the basis under the list when rows carry counts', async () => {
    const t = await mount(base(FOLDERS))
    expect(t).toContain('128 items')
    expect(t).toContain(SIZE_HINT_BASIS)
  })

  it('says nothing when the provider returns no counts', async () => {
    // Google Drive's case. A caption explaining figures nobody can see is furniture, and furniture
    // is what trains a reader to skip the box that one day carries a real caveat.
    const t = await mount(base(NO_COUNTS))
    expect(t).toContain('HR')
    expect(t).not.toContain(SIZE_HINT_BASIS)
  })

  it('is the SAME sentence the row tooltip uses', () => {
    // One constant, one claim. A second wording here would be a second claim about one number, and
    // the two would drift in the direction that makes the count sound like a file count.
    expect(SIZE_HINT_BASIS).toMatch(/not a recursive file count/i)
    expect(SIZE_HINT_BASIS).toMatch(/including subfolders/i)
  })

  it('and the hint itself still says "items", never "files"', () => {
    // The distinction the caption exists to protect.
    expect(sizeHint({ child_count: 128 })).toBe('128 items')
    expect(sizeHint({ child_count: 1 })).toBe('1 item')
    expect(sizeHint({})).toBe(null)
  })
})

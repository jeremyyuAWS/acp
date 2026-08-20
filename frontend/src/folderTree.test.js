/**
 * Tri-state and folder size in a picker that holds one level of the tree.
 *
 * Item 4 of the wizard review asked for both. The interesting part of implementing them was
 * finding where each stops being knowable:
 *
 *   · tri-state is NOT derivable in general — FolderPicker drills rather than expands, so it never
 *     holds the descendants a "some selected" state would have to be computed from. It IS exact in
 *     the one case that matters, because a carve-out can only be made while inside an included
 *     folder, and that ancestor can be recorded at the moment it is known.
 *
 *   · "~120 files" does not exist. Google Drive's /folders returns id and name only; SharePoint
 *     returns Graph's `folder.childCount`, which counts subfolders as items and does not recurse.
 *     Presenting it as a file count would be wrong in unit AND in depth, on the screen that
 *     decides what gets scanned.
 *
 * The negative cases below are the point of the file.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  excludeUnder, isPartlySelected, checkboxState, sizeHint, SIZE_HINT_BASIS,
} from './folderTree.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

const PICKED = [{ id: 'prog', name: 'Accessibility Program' }]
const EXC_UNDER_PROG = [{ id: 'arch', name: 'Archive', under: 'prog' }]

describe('recording which folder a carve-out narrows', () => {
  const stack = [{ id: 'root' }, { id: 'prog' }, { id: 'sub' }]
  const isPicked = (id) => id === 'prog'

  it('names the nearest included ancestor from the live breadcrumb', () => {
    expect(excludeUnder(stack, isPicked)).toBe('prog')
  })

  it('prefers the NEAREST when two ancestors are included', () => {
    // Excluding under the deeper one is what the user is looking at; attributing it to the
    // shallower would mark the wrong folder partial.
    expect(excludeUnder(stack, (id) => id === 'prog' || id === 'root')).toBe('prog')
  })

  it('returns null when nothing above is included', () => {
    // Not reachable through the UI — you cannot exclude outside an inclusion — but a null here is
    // a recorded absence, which isPartlySelected then ignores rather than guessing about.
    expect(excludeUnder(stack, () => false)).toBeNull()
  })
})

describe('partial selection', () => {
  it('is true for an included folder with a carve-out inside it', () => {
    expect(isPartlySelected('prog', PICKED, EXC_UNDER_PROG)).toBe(true)
  })

  it('is false for an included folder with no carve-out', () => {
    expect(isPartlySelected('prog', PICKED, [])).toBe(false)
  })

  it('is false for a folder nobody included', () => {
    // An unexpanded folder with unknown descendants is not "partially selected", it is a folder
    // nobody has looked inside. Claiming partial there is the guess this module refuses to make.
    expect(isPartlySelected('finance', PICKED, EXC_UNDER_PROG)).toBe(false)
  })

  it('ignores a carve-out recorded under a DIFFERENT folder', () => {
    expect(isPartlySelected('prog', PICKED, [{ id: 'x', under: 'other' }])).toBe(false)
  })

  it('ignores a legacy exclusion with no recorded ancestor', () => {
    // Restored from a scope saved before `under` existed. Absent, not assumed.
    expect(isPartlySelected('prog', PICKED, [{ id: 'arch', name: 'Archive' }])).toBe(false)
  })

  it('survives missing lists rather than throwing', () => {
    expect(isPartlySelected('prog', null, null)).toBe(false)
    expect(isPartlySelected(null, PICKED, EXC_UNDER_PROG)).toBe(false)
  })
})

describe('what the checkbox renders', () => {
  const isExcluded = (id) => id === 'arch'

  it('is partial for the included folder holding a carve-out', () => {
    expect(checkboxState({ id: 'prog' }, { picked: PICKED, excluded: EXC_UNDER_PROG, inherited: false, isExcluded }))
      .toBe('partial')
  })

  it('is on for a plainly included folder', () => {
    expect(checkboxState({ id: 'prog' }, { picked: PICKED, excluded: [], inherited: false, isExcluded }))
      .toBe('on')
  })

  it('is off for an unselected folder', () => {
    expect(checkboxState({ id: 'fin' }, { picked: PICKED, excluded: [], inherited: false, isExcluded }))
      .toBe('off')
  })

  it('stays binary inside an inherited folder', () => {
    // Within an included parent the checkbox means include/exclude THIS row. A third state there
    // would be a different question than the one the control is asking.
    expect(checkboxState({ id: 'arch' }, { picked: PICKED, excluded: EXC_UNDER_PROG, inherited: true, isExcluded }))
      .toBe('off')
    expect(checkboxState({ id: 'other' }, { picked: PICKED, excluded: EXC_UNDER_PROG, inherited: true, isExcluded }))
      .toBe('on')
  })
})

describe('the size hint', () => {
  it('says "items", never "files"', () => {
    // Graph's childCount counts subfolders as items and does not recurse. "120 files" would be
    // wrong in unit and in depth.
    const h = sizeHint({ id: 'a', child_count: 120 })
    expect(h).toBe('120 items')
    expect(h, 'childCount was presented as a file count').not.toMatch(/file/i)
  })

  it('pluralises, because "1 items" undercuts the number beside it', () => {
    expect(sizeHint({ id: 'a', child_count: 1 })).toBe('1 item')
  })

  it('shows zero rather than hiding it — empty is a useful fact here', () => {
    expect(sizeHint({ id: 'a', child_count: 0 })).toBe('0 items')
  })

  it('is absent when the provider gave no count', () => {
    // Google Drive's /folders returns id and name only. No hint beats a hint that means something
    // different depending on which source you are looking at.
    expect(sizeHint({ id: 'a', name: 'Finance' })).toBeNull()
    expect(sizeHint({ id: 'a', child_count: null })).toBeNull()
    expect(sizeHint(null)).toBeNull()
  })

  it('explains what the number is NOT', () => {
    expect(SIZE_HINT_BASIS).toMatch(/including subfolders/i)
    expect(SIZE_HINT_BASIS).toMatch(/[Nn]ot a recursive file count/)
  })
})

describe('the picker actually uses this', () => {
  const src = read('FolderPicker.jsx')

  it('records the ancestor when a carve-out is made', () => {
    expect(src).toMatch(/under: excludeUnder\(stack, isPicked\)/)
  })

  it('sets indeterminate on the DOM node, which markup cannot do', () => {
    expect(src).toMatch(/el\.indeterminate = tri === 'partial'/)
    expect(src).toMatch(/aria-checked=\{tri === 'partial' \? 'mixed' : undefined\}/)
  })

  it('renders the size hint with its basis as the tooltip', () => {
    expect(src).toMatch(/title=\{SIZE_HINT_BASIS\}/)
    expect(src).toMatch(/\{sizeHint\(f\)\}/)
  })

  it('gives the browser 65 and the summary 35', () => {
    expect(src).toMatch(/flex: '65 1 320px'/)
    expect(src).toMatch(/flex: '35 1 240px'/)
  })
})

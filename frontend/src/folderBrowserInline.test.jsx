/**
 * The inline two-column folder browser — step 1 of the scan wizard.
 *
 * WHAT CHANGED AND WHY. Choosing folders used to be a link ("Choose folders…") that opened a
 * modal on top of the wizard. That made the two halves of ONE decision sequential: you ticked
 * inside a dialog, saved, closed it, and only then read a row of chips on the screen underneath.
 * The scope you were assembling was never on screen while you were assembling it — and it became
 * visible at exactly the moment it had stopped being cheap to change.
 *
 * Two columns, both always visible: tree on the left, the scope you have built on the right. An
 * over-wide selection is now something you SEE, not something a count tells you about afterwards.
 *
 * WHAT THESE CASES STOP, all of which look fine on screen:
 *
 *   · the inline mode reporting nothing until a confirm that does not exist — the wizard's footer
 *     is the only footer, so a selection that waits for a Save is a selection that never arrives,
 *     and the run silently covers the whole Drive
 *   · the mount echo: the picker handing `initial` straight back to a parent still loading its
 *     saved folders, overwriting a real selection with an empty list. Empty means EVERYTHING here,
 *     so that failure widens the scan — the direction nobody re-checks
 *   · "Clear all" clearing the inclusions but leaving the carve-outs, so an exclusion re-arms the
 *     next time somebody picks a folder above it — narrowing chosen for a different scope
 *   · the filter reading as a search of the whole Drive. It filters the rows already listed for
 *     THIS folder; a user who concludes "no such folder" from it and scans everything instead has
 *     been misled by a control that returned a correct answer to a different question
 *   · a filter surviving a drill-down, so a folder you just opened reads as empty
 *   · the empty scope panel going blank, which reads as "nothing will be scanned" when it means
 *     the exact opposite
 *
 * DOM-level, not browser-level: the preview server is rooted at the SHARED checkout whatever
 * worktree you are in (CLAUDE.md), so a browser check would exercise code without this change.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

vi.mock('./api.js', () => ({
  getSettings: vi.fn(async () => ({ scan_scope: '' })),
  updateSettings: vi.fn(async () => ({ scan_scope: '' })),
  getScanLocations: vi.fn(async () => ({ locations: {} })),
  setScanLocations: vi.fn(async () => ({ ok: true })),
  // Root lists two; drilling into either lists one child.
  listFolders: vi.fn(async (parent) => (parent === 'root'
    ? { folders: [{ id: 'hr', name: 'HR' }, { id: 'fin', name: 'Finance' }] }
    : { folders: [{ id: 'arch', name: 'Archive' }] })),
  listSpFolders: vi.fn(async () => ({ drive_id: 'd', folders: [] })),
}))

const { default: FolderPicker } = await import('./FolderPicker.jsx')
const { default: ScanScopeWizard } = await import('./ScanScopeWizard.jsx')

async function inline(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(FolderPicker, { layout: 'inline', rootName: 'My Drive', ...props }))
  })
  return container
}

const boxes = (c) => [...c.querySelectorAll('input[type="checkbox"]')]
const byLabel = (c, re) => boxes(c).find((b) => re.test(b.getAttribute('aria-label') || ''))
const btn = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent))
const scopePanel = (c) => c.querySelector('[role="region"][aria-label="Current scope"]')
const filterInput = (c) => [...c.querySelectorAll('input')]
  .find((i) => /^Filter folders in /.test(i.getAttribute('aria-label') || ''))

async function type(input, value) {
  // React tracks the last value it wrote, so a bare `.value =` is swallowed as a no-op change.
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  setter.call(input, value)
  await act(async () => { input.dispatchEvent(new window.Event('input', { bubbles: true })) })
}

describe('the inline layout is a panel, not a dialog', () => {
  it('drops the overlay chrome so it can sit inside the wizard', async () => {
    // A dialog nested in the wizard would put two competing footers and two Escape targets on one
    // screen. The point of the inline mode is that the wizard keeps owning the flow.
    const c = await inline()
    expect(c.querySelector('[role="dialog"]')).toBeNull()
    expect(c.querySelector('.setoverlay')).toBeNull()
    expect(btn(c, /^Save/)).toBeFalsy()
    expect(btn(c, /Scan all of/)).toBeFalsy()
  })

  it('shows the tree and the scope it builds at the same time', async () => {
    // The whole reason for the layout. If either half can be off-screen, this is the modal again
    // with different padding.
    const c = await inline()
    expect(btn(c, /HR/), 'no folder list').toBeTruthy()
    const panel = scopePanel(c)
    expect(panel, 'no Current scope panel').toBeTruthy()
    expect(panel.textContent).toMatch(/all of My Drive/)
  })

  it('says what an empty scope MEANS rather than rendering blank', async () => {
    // "Nothing selected" and "everything" are the same blank panel otherwise, and the reassuring
    // reading is the wrong one.
    const c = await inline()
    expect(scopePanel(c).textContent).toMatch(/Nothing selected/)
    expect(scopePanel(c).textContent).toMatch(/all of My Drive/)
  })
})

describe('the selection reaches the parent as it is made', () => {
  it('reports on every tick, with no confirm step', async () => {
    // THE load-bearing case. There is no Save in this layout, so a picker that only reports at a
    // confirm reports never — and the wizard starts a scan with the empty scope, which means
    // EVERYTHING.
    const seen = []
    const c = await inline({ onChange: (inc, exc) => seen.push([inc, exc]) })
    await act(async () => { byLabel(c, /Select HR/).click() })
    expect(seen.length).toBe(1)
    expect(seen[0][0].map((f) => f.id)).toEqual(['hr'])
    expect(seen[0][0][0].name).toBe('HR')      // named, so a chip is not an opaque Drive id
    await act(async () => { byLabel(c, /Select Finance/).click() })
    expect(seen[1][0].map((f) => f.id)).toEqual(['hr', 'fin'])
  })

  it('does NOT report on mount', async () => {
    // The mount echo hands `initial` back to a parent that may still be loading its saved value.
    // Because empty means everything, the damage is a silently WIDENED scan.
    const seen = []
    await inline({ onChange: (...a) => seen.push(a) })
    expect(seen.length).toBe(0)
  })

  it('reports exclusions alongside the inclusions', async () => {
    const seen = []
    const c = await inline({ initial: [{ id: 'hr', name: 'HR' }],
                             onChange: (inc, exc) => seen.push([inc, exc]) })
    await act(async () => { btn(c, /HR/).click() })       // drill in; Archive is inherited-included
    await act(async () => { byLabel(c, /Exclude Archive/).click() })
    expect(seen.at(-1)[0].map((f) => f.id)).toEqual(['hr'])
    expect(seen.at(-1)[1].map((f) => f.id)).toEqual(['arch'])
    expect(scopePanel(c).textContent).toMatch(/except Archive/)
  })
})

describe('Clear all', () => {
  it('clears the carve-outs with the inclusions', async () => {
    // An exclusion left behind re-arms the moment somebody picks a folder containing it — a
    // narrowing nobody chose, carried over from a decision about a different scope. The backend
    // already drops exclusions with no inclusions (drive.py); the surface must not disagree.
    const seen = []
    const c = await inline({ initial: [{ id: 'hr', name: 'HR' }],
                             initialExclude: [{ id: 'arch', name: 'Archive' }],
                             onChange: (inc, exc) => seen.push([inc, exc]) })
    expect(scopePanel(c).textContent).toMatch(/except Archive/)
    await act(async () => { btn(c, /Clear all/).click() })
    expect(seen.at(-1)).toEqual([[], []])
    expect(scopePanel(c).textContent).toMatch(/Nothing selected/)
  })

  it('is not offered when there is nothing to clear', async () => {
    const c = await inline()
    expect(btn(c, /Clear all/)).toBeFalsy()
  })
})

describe('the filter is scoped to this folder, and says so', () => {
  it('narrows the list', async () => {
    const c = await inline()
    await type(filterInput(c), 'fin')
    expect(byLabel(c, /Select Finance/)).toBeTruthy()
    expect(byLabel(c, /Select HR/), 'HR still listed under a "fin" filter').toBeFalsy()
  })

  it('states the boundary of what it filtered', async () => {
    // Without this line the control reads as a search of the whole Drive. The result would be
    // correct and the conclusion drawn from it wrong — a folder that exists elsewhere reads as
    // absent, and the user gives up and scans everything.
    const c = await inline()
    await type(filterInput(c), 'fin')
    expect(c.textContent).toMatch(/1 of 2/)
    expect(c.textContent).toMatch(/filters this folder only/)
    expect(c.textContent).toMatch(/does not search subfolders/)
  })

  it('distinguishes "no match" from "no subfolders"', async () => {
    const c = await inline()
    await type(filterInput(c), 'zzz')
    expect(c.textContent).toMatch(/matches/)
    expect(c.textContent).not.toMatch(/No subfolders here/)
  })

  it('resets when you drill into a folder', async () => {
    // A filter that survives the move hides rows in a folder you just opened, and the folder reads
    // as empty — the one wrong answer the picker must never give, because the fix (widening) is
    // the expensive direction.
    const c = await inline()
    await type(filterInput(c), 'hr')
    await act(async () => { btn(c, /HR/).click() })
    expect(filterInput(c).value).toBe('')
    expect(btn(c, /Archive/), 'child hidden by a stale filter').toBeTruthy()
  })
})

// ── mounted in the wizard ────────────────────────────────────────────────────────────────────

describe('step 1 of the wizard mounts the browser inline', () => {
  async function wizard() {
    const { root, container } = createTestRoot()
    await act(async () => {
      root.render(createElement(ScanScopeWizard, {
        showStartButton: true, source: 'drive', hasDrive: true, hasSP: false,
        onStartScan: () => {},
      }))
    })
    return container
  }

  it('offers "Entire connected source" first and browses nothing until asked', async () => {
    const c = await wizard()
    expect(c.textContent).toMatch(/Entire source/)
    expect(scopePanel(c), 'browser shown before the user chose to narrow').toBeFalsy()
  })

  it('shows the two-column browser once "Specific folders" is chosen', async () => {
    const c = await wizard()
    await act(async () => { btn(c, /Specific folders/).click() })
    expect(scopePanel(c), 'no inline browser on step 1').toBeTruthy()
    expect(btn(c, /Choose folders…|Change…/), 'the modal link is back').toBeFalsy()
  })

  it('carries a folder ticked inline through to the scan it starts', async () => {
    // End to end for the thing that actually matters: a tick in step 1 has to be in the scope the
    // run freezes (scan_runs.scope, ADR 0035). If it stops at the picker, the review step and the
    // run describe different estates and the count has the wrong boundary printed on it.
    const seen = []
    const { root, container: c } = createTestRoot()
    await act(async () => {
      root.render(createElement(ScanScopeWizard, {
        showStartButton: true, source: 'drive', hasDrive: true, hasSP: false,
        onStartScan: (o) => seen.push(o),
      }))
    })
    await act(async () => { btn(c, /Specific folders/).click() })
    await act(async () => { byLabel(c, /Select HR/).click() })
    for (let i = 0; i < 2; i++) {
      const cont = btn(c, /Continue/)
      if (!cont) break
      // eslint-disable-next-line no-await-in-loop
      await act(async () => { cont.click() })
    }
    await act(async () => { btn(c, /Start scan/).click() })
    expect(seen[0].folders.map((f) => f.id)).toEqual(['hr'])
  })
})

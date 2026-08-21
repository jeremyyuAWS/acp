/**
 * The wizard must not let an empty "Specific folders" selection start a whole-estate scan.
 *
 * The unit cases in wizardScopeReady.test.js prove the predicate. They cannot prove the wizard
 * ASKS it, and that gap is exactly how #491's gate survived deletion with 2342 tests green. This
 * file mounts the thing and asserts what a user would see:
 *
 *   · Continue is genuinely disabled while narrowing with nothing selected
 *   · it becomes available again the moment a folder is ticked      ← the control case
 *   · it is available in "Entire source", which is a legitimate empty
 *   · the scope panel stops offering "covers all of OneDrive" as the reading of that empty
 *
 * The control case matters most: asserting only the disabled state would pass if the button never
 * rendered at all, which is the shape of test that fooled itself in drawerErrorReason.test.jsx.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

vi.mock('./api.js', () => ({
  getSettings: vi.fn(async () => ({ scan_scope: '' })),
  updateSettings: vi.fn(async () => ({ scan_scope: '' })),
  getScanLocations: vi.fn(async () => ({ locations: { drive: [], _exclude: { drive: [] } } })),
  setScanLocations: vi.fn(async () => ({ ok: true })),
  listFolders: vi.fn(async () => ({ folders: [{ id: 'fin', name: 'Finance' }] })),
  listSpFolders: vi.fn(async () => ({ drive_id: 'd', folders: [] })),
  // Discovery-time lifecycle rules, read by the review step so it can name how many will
  // run. Empty is the honest default here: these fixtures configure no rule.
  listDispositionPolicies: vi.fn(async () => []),
}))

const { default: ScanScopeWizard } = await import('./ScanScopeWizard.jsx')

async function mount() {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(ScanScopeWizard, {
      showStartButton: true, source: 'drive', hasDrive: true, hasSP: false,
      onStartScan: () => {},
    }))
  })
  return container
}

const btn = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent))
// The primary action — by its stable hook, and deliberately WITHOUT navigating anywhere.
//
// This file is about step 1's gate: "Specific folders" chosen with none selected falls through to
// the WHOLE source, so the forward control must refuse (#502). Walking past it is the one thing
// these cases must not do, and a finder that matched the button by label would have to be updated
// every time the label changes — which it just did, from "Start discovery" to the per-step
// "Continue to rules →".
const continueBtn = (c) => c.querySelector('button[data-wizard-forward]')
const modeBtn = (c, label) => [...c.querySelectorAll('[role="radio"]')]
  .find((b) => b.textContent.includes(label))

async function chooseSpecificFolders(c) {
  const m = modeBtn(c, 'Specific folders')
  expect(m, 'the "Specific folders" mode control is not on screen').toBeTruthy()
  await act(async () => { m.click() })
}

describe('narrowing with nothing selected', () => {
  it('disables the primary action instead of scanning everything', async () => {
    const c = await mount()
    await chooseSpecificFolders(c)
    const b = continueBtn(c)
    expect(b, 'there is no primary action to assert about').toBeTruthy()
    expect(b.disabled, 'the primary action is live over an empty "Specific folders" selection').toBe(true)
  })

  it('says why, rather than leaving a dead button', async () => {
    const c = await mount()
    await chooseSpecificFolders(c)
    expect(continueBtn(c).title).toMatch(/at least one folder/)
  })

  it('stops telling the user this covers everything', async () => {
    const c = await mount()
    await chooseSpecificFolders(c)
    expect(c.textContent, 'the empty selection still claims the whole source')
      .not.toMatch(/scan covers/)
    expect(c.textContent).toMatch(/Select at least one folder/)
  })

  it('no longer contradicts itself in the footer', async () => {
    const c = await mount()
    await chooseSpecificFolders(c)
    expect(c.textContent, 'the footer still reads "Entire source" while narrowing')
      .not.toMatch(/Entire source ·/)
  })
})

describe('the states that must stay available', () => {
  it('the primary action works in "Entire source", where empty is the honest answer', async () => {
    // The control. If the block fired here it would be unusable, and this is also the assertion
    // that proves the disabled cases above are not just "the button is always disabled".
    const c = await mount()
    const m = modeBtn(c, 'Entire connected source')
    if (m) await act(async () => { m.click() })
    expect(continueBtn(c).disabled, 'the primary action is blocked in the entire-source mode').toBe(false)
  })

  it('the primary action returns as soon as a folder is ticked', async () => {
    const c = await mount()
    await chooseSpecificFolders(c)
    expect(continueBtn(c).disabled).toBe(true)

    // The checkbox, NOT the row button: the picker deliberately separates selecting from drilling
    // in ("one control doing both is the picker bug where opening a folder to look inside it
    // silently changes what you are about to scan"). Asserted rather than guarded with `if` —
    // a test that skips itself when it cannot find its target is a test that cannot fail.
    const box = c.querySelector('input[type="checkbox"][aria-label="Select Finance"]')
    expect(box, 'the folder checkbox is not on screen — the test cannot exercise selection')
      .toBeTruthy()
    await act(async () => { box.click() })
    expect(continueBtn(c).disabled, 'the primary action stayed blocked after a folder was selected')
      .toBe(false)
  })
})

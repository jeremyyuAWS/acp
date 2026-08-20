/**
 * "Reuse a recent scope" in step 1, and the criteria write-back it sits above.
 *
 * A shortcut's whole risk is that it is clicked without being read, so what is guarded here is
 * what the shortcut must never do quietly:
 *
 *   · apply a scope and leave the browser below still showing the previous one. The inline picker
 *     seeds from `initial` at MOUNT, so a reuse that does not remount it puts two answers to
 *     "what am I about to scan?" on one screen — the failure the two-column layout exists to
 *     remove, re-introduced by the control meant to make it faster.
 *   · drop the carve-outs. A run records exclusion IDS with no names; carrying the ids and losing
 *     the names is a display problem, losing the ids is a WIDER SCAN behind a control labelled as
 *     a narrowing.
 *   · offer a run whose scope was never recorded. NULL is unknown, and applying unknown applies
 *     as everything.
 *   · be shown for a source it cannot apply to. Drive folder ids are not Graph
 *     `<driveId>/<itemId>` pairs; they would be accepted, resolve to nothing, and the run would
 *     come back empty with a boundary that looks deliberate.
 *
 * And the criteria write-back, which this change makes symmetric with the folder one:
 *
 *   · it used to be ticked BY DEFAULT and shown on every run, while calling itself "my next
 *     scan". It is the platform default and applies to everyone, so on-by-default turned a
 *     one-off narrowing into permanent configuration for the whole tenant unless somebody noticed
 *     a ticked box. That is the identical failure the folder write-back is careful about, with
 *     the default the wrong way round.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const updateSettings = vi.fn(async () => ({ scan_scope: '' }))

vi.mock('./api.js', () => ({
  getSettings: vi.fn(async () => ({ scan_scope: '' })),
  updateSettings: (...a) => updateSettings(...a),
  getScanLocations: vi.fn(async () => ({ locations: {} })),
  setScanLocations: vi.fn(async () => ({ ok: true })),
  listFolders: vi.fn(async (parent) => (parent === 'root'
    ? { folders: [{ id: 'hr', name: 'HR' }, { id: 'fin', name: 'Finance' }] }
    : { folders: [{ id: 'arch', name: 'Archive' }] })),
  listSpFolders: vi.fn(async () => ({ drive_id: 'd', folders: [] })),
}))

const { default: ScanScopeWizard } = await import('./ScanScopeWizard.jsx')

const RUN_HR = {
  id: 'r1', completed_at: '2026-08-18T10:00:00Z', source: 'drive',
  scope: { kind: 'folder', folders: [{ id: 'hr', name: 'HR' }], excluded: ['arch'] },
}
const RUN_FIN_PDF = {
  id: 'r2', completed_at: '2026-08-10T10:00:00Z', source: 'drive',
  scope: { kind: 'folder', folders: [{ id: 'fin', name: 'Finance' }], scan_scope: { '1.1.1': ['pdf'] } },
}

async function mount(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(ScanScopeWizard, {
      showStartButton: true, source: 'drive', hasDrive: true, hasSP: false,
      onStartScan: () => {}, scans: [RUN_HR, RUN_FIN_PDF], ...props,
    }))
  })
  return container
}

const btn = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent))
const chip = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent) && b.hasAttribute('aria-pressed'))
const scopePanel = (c) => c.querySelector('[role="region"][aria-label="Current scope"]')

describe('the shortcuts that are offered', () => {
  it('lists the boundaries this user has actually run, newest first', async () => {
    const c = await mount()
    // The block is now a collapsed disclosure BELOW the selection rather than a row of cards above
    // it — past scopes are an accelerator, not the decision the user came to make.
    expect(c.textContent).toMatch(/Use a recent scope/)
    expect(c.querySelector('details'), 'the recent scopes are no longer collapsed').toBeTruthy()
    expect(chip(c, /HR/), 'no chip for the HR run').toBeTruthy()
    expect(chip(c, /Finance/), 'no chip for the Finance run').toBeTruthy()
  })

  it('names both halves of the boundary on the chip', async () => {
    // A reader given locations without criteria cannot reconstruct what was measured, which is
    // why the run records the two together.
    const c = await mount()
    expect(chip(c, /HR/).textContent).toMatch(/Everything supported/)
    expect(chip(c, /Finance/).textContent).toMatch(/1 criteria/)
  })

  it('says the carve-out is there without printing a raw id', async () => {
    const c = await mount()
    const t = chip(c, /HR/).textContent
    expect(t).toMatch(/except 1 folder \(not named on that run\)/)
    expect(t, 'a Drive id leaked onto the chip').not.toMatch(/\barch\b/)
  })

  it('offers nothing when no run recorded a scope', async () => {
    // NULL is unknown, not "the whole Drive". A chip here would apply as everything.
    const c = await mount({ scans: [{ id: 'x', completed_at: '2026-08-18T10:00:00Z', source: 'drive', scope: null }] })
    // Asserted against the CURRENT label. The old all-caps heading no longer exists anywhere, so
    // matching on it would have passed whatever the block did — a check that cannot fail.
    expect(c.textContent).not.toMatch(/Use a recent scope/)
  })

  it('offers nothing from the other source family', async () => {
    const c = await mount({ source: 'sharepoint', hasDrive: false, hasSP: true })
    // Asserted against the CURRENT label. The old all-caps heading no longer exists anywhere, so
    // matching on it would have passed whatever the block did — a check that cannot fail.
    expect(c.textContent).not.toMatch(/Use a recent scope/)
  })
})

describe('applying one', () => {
  it('shows the applied scope in the browser below, not the previous one', async () => {
    // THE load-bearing case. The inline picker seeds from `initial` at mount, so without a
    // remount the chips keep saying what the wizard no longer means.
    const c = await mount()
    await act(async () => { chip(c, /HR/).click() })
    const panel = scopePanel(c)
    expect(panel, 'reuse did not switch step 1 into the folder browser').toBeTruthy()
    expect(panel.textContent).toMatch(/HR/)
    // And switching to the other one has to move it again — a seed that only bumps once looks
    // right on the first click and stales on the second.
    await act(async () => { chip(c, /Finance/).click() })
    expect(scopePanel(c).textContent).toMatch(/Finance/)
    expect(scopePanel(c).textContent).not.toMatch(/📁 HR/)
  })

  it('starts the scan with the reused folders AND the reused carve-out', async () => {
    const seen = []
    const c = await mount({ onStartScan: (o) => seen.push(o) })
    await act(async () => { chip(c, /HR/).click() })
    for (let i = 0; i < 2; i++) {
      const cont = btn(c, /Continue/)
      if (!cont) break
      // eslint-disable-next-line no-await-in-loop
      await act(async () => { cont.click() })
    }
    await act(async () => { btn(c, /Start scan/).click() })
    expect(seen[0].folders.map((f) => f.id)).toEqual(['hr'])
    // Carried, not dropped. Dropping it would widen the run behind a control labelled as a
    // narrowing — and the review step would still have said "1 excluded".
    expect(seen[0].exclude.map((f) => f.id)).toEqual(['arch'])
  })

  it('applies the reused criteria too', async () => {
    const c = await mount()
    await act(async () => { chip(c, /Finance/).click() })
    await act(async () => { btn(c, /Continue/).click() })
    // Step 2 now reflects a restricted scope rather than "everything supported".
    expect(c.textContent).not.toMatch(/53 supported checks selected/)
  })

  it('says the reuse is a starting point, not a verification', async () => {
    const c = await mount()
    await act(async () => { chip(c, /HR/).click() })
    // "above" now: the selection is above the disclosure, not below it.
    expect(c.textContent).toMatch(/check the locations and criteria above/i)
  })
})

describe('the criteria write-back is opt-in and only on divergence', () => {
  async function toReview(c) {
    for (let i = 0; i < 2; i++) {
      const cont = btn(c, /Continue/)
      if (!cont) break
      // eslint-disable-next-line no-await-in-loop
      await act(async () => { cont.click() })
    }
  }

  it('is absent when this run matches what is stored', async () => {
    // A control that is always there is a control people tick without reading; its ABSENCE is
    // itself the signal that nothing would be written.
    const c = await mount()
    await toReview(c)
    expect(c.textContent).not.toMatch(/save these criteria as the platform default/)
  })

  it('appears once the criteria differ, unticked, and says who it affects', async () => {
    const c = await mount()
    await act(async () => { chip(c, /Finance/).click() })
    await toReview(c)
    const box = [...c.querySelectorAll('input[type="checkbox"]')].pop()
    expect(c.textContent).toMatch(/save these criteria as the platform default/)
    expect(box.checked, 'the platform-wide write-back is ticked by default').toBe(false)
    // "my next scan" was a misdescription: scan_scope is the platform default for everyone.
    expect(c.textContent).toMatch(/for everyone/)
  })

  it('does not write the platform default unless it is ticked', async () => {
    // The load-bearing one. A one-off narrowing must not become configuration for the tenant.
    updateSettings.mockClear()
    const c = await mount()
    await act(async () => { chip(c, /Finance/).click() })
    await toReview(c)
    await act(async () => { btn(c, /Start scan/).click() })
    expect(updateSettings).not.toHaveBeenCalled()
  })

  it('is not offered at all to an account that cannot write it', async () => {
    // PUT /settings is admin-only. Showing the box to a read-only account promises a write that
    // 403s after the modal has closed.
    const c = await mount({ canEditScope: false })
    await act(async () => { chip(c, /Finance/).click() })
    await toReview(c)
    expect(c.textContent).not.toMatch(/save these criteria as the platform default/)
  })
})

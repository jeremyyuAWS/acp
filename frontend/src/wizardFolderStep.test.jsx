/**
 * Folders as step 1 of the scan wizard — and the rule that stops two stores disagreeing.
 *
 * The Sources card holds a folder set per CONNECTION; this wizard chooses one per RUN. Two stores
 * with no stated relationship is how the card ends up reading "Scans: HR" while last night's run
 * covered the whole Drive — and anyone using the card to interpret that run's count reads the
 * wrong boundary. It is the 2026-07-30 defect (frontend/src/scanScope.js) with the mismatch moved
 * one level up, from scan-vs-estate to config-vs-run.
 *
 * THE RULE, decided 2026-08-19:
 *
 *   card seeds the wizard  ->  they agree unless somebody deliberately diverges them
 *   a change is THIS RUN   ->  a one-off cannot silently reconfigure the connection
 *   write-back is a tick   ->  and only appears once the two actually differ
 *
 * The middle line is the one with teeth. Writing back automatically would mean "let me just check
 * HR quickly" permanently narrows every later scheduled scan — narrowing nobody chose, invisible
 * because it then looks like configuration somebody set on purpose. That is the direction nobody
 * re-checks, so it is the direction the tests guard hardest.
 *
 * It is also the rule this screen already uses for criteria ("Remember these selections for my
 * next scan"), so the two halves of the wizard behave the same way rather than teaching two.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { gotoStep } from './wizardNav.testkit.js'

afterEach(unmountAll)

const SAVED = [{ id: 'hr', name: 'HR' }]
const setScanLocations = vi.fn(async () => ({ ok: true }))

vi.mock('./api.js', () => ({
  getSettings: vi.fn(async () => ({ scan_scope: '' })),
  updateSettings: vi.fn(async () => ({ scan_scope: '' })),
  getScanLocations: vi.fn(async () => ({ locations: { drive: SAVED, _exclude: { drive: [] } } })),
  setScanLocations: (...a) => setScanLocations(...a),
  listFolders: vi.fn(async () => ({ folders: [{ id: 'fin', name: 'Finance' }] })),
  listSpFolders: vi.fn(async () => ({ drive_id: 'd', folders: [] })),
  // Discovery-time lifecycle rules, read by the review step so it can name how many will
  // run. Empty is the honest default here: these fixtures configure no rule.
  listDispositionPolicies: vi.fn(async () => []),
}))

const { default: ScanScopeWizard, locationsKeyFor } = await import('./ScanScopeWizard.jsx')

async function mount(onStartScan = () => {}, props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(ScanScopeWizard, {
      showStartButton: true, source: 'drive', hasDrive: true, hasSP: false,
      onStartScan, ...props,
    }))
  })
  return container
}

const btn = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent))
// The run control lives on step 3 now (Source and folders → Lifecycle rules → Review and run), so
// a case that clicks it walks there first. By the stable hook rather than the label: the forward
// control's text is per-step data ("Run discovery →" at the end), and none of these cases is about
// what it says.
const runDiscovery = async (c) => {
  await gotoStep(c, act, 3)
  return c.querySelector('button[data-wizard-forward]')
}

// Start lives on step 3 of the wizard now. Walking there is what a user does, so the tests do it
// too rather than reaching past the flow.
async function toStart(c) {
  for (let i = 0; i < 2; i++) {
    const cont = btn(c, /Continue/)
    if (!cont) break
    // eslint-disable-next-line no-await-in-loop
    await act(async () => { cont.click() })
  }
  return runDiscovery(c)
}

describe('the card seeds the wizard', () => {
  it('shows the connection default rather than an empty scope', async () => {
    // If it opened empty, the user would see "entire source" and believe it — while the card said
    // HR. The two must not disagree before anyone has touched anything.
    const c = await mount()
    expect(c.textContent).toContain('HR')
  })

  it('says "entire source" out loud when nothing is saved', async () => {
    // Blank and "everything" look identical otherwise, and the reassuring reading of a blank row
    // is the wrong one.
    const { getScanLocations } = await import('./api.js')
    getScanLocations.mockResolvedValueOnce({ locations: {} })
    const c = await mount()
    expect(c.textContent).toMatch(/Entire source/i)
  })
})

describe('a change applies to this run only', () => {
  it('hands the chosen folders to the caller', async () => {
    const seen = []
    const c = await mount((o) => seen.push(o))
    const start = await toStart(c)
    await act(async () => { start.click() })
    expect(seen[0]).toMatchObject({ folders: SAVED })
  })

  it('does NOT write back to the connection by default', async () => {
    // THE load-bearing case. Automatic write-back turns a one-off narrow scan into permanent
    // configuration, and every later scheduled scan silently covers less.
    setScanLocations.mockClear()
    const c = await mount()
    const start = await toStart(c)
    await act(async () => { start.click() })
    expect(setScanLocations).not.toHaveBeenCalled()
  })

  it('offers the write-back only once the run differs from the card', async () => {
    // A checkbox that is always there is a checkbox people tick without reading. It appears at
    // the moment it means something — and its absence is itself the signal that the run matches
    // the source.
    const c = await mount()
    expect(c.textContent).not.toMatch(/save as the default/i)
  })
})

describe('an explicit tile click survives the saved-scope fetch resolving later', () => {
  // Found live 2026-08-21: scopeMode starts 'all' ("Entire connected source" renders first,
  // purple-highlighted), then getScanLocations resolves ~1s later and — whenever the source has
  // a saved folder set — silently flips scopeMode to 'some', with no check for whether the user
  // already picked a tile in the meantime. Reproduced twice live: clicking "Entire connected
  // source" during that window, then Continue, actually proceeded with the OLD saved folder
  // scope. These hold the fetch open with an uncontrolled promise to land a click inside the
  // exact race window, then resolve it and confirm the explicit choice won.
  const radio = (c, name) => [...c.querySelectorAll('[role="radio"]')]
    .find((b) => b.textContent.includes(name))

  it('clicking "Entire connected source" before the fetch resolves is not clobbered once it does', async () => {
    const { getScanLocations } = await import('./api.js')
    let resolveFetch
    getScanLocations.mockReturnValueOnce(new Promise((r) => { resolveFetch = r }))
    const c = await mount()

    // The fetch is still pending — scopeMode is at its 'all' default. Click it explicitly.
    await act(async () => { radio(c, 'Entire connected source').click() })
    expect(radio(c, 'Entire connected source').getAttribute('aria-checked')).toBe('true')

    // Now the saved-scope fetch resolves, with a non-empty folder set that would otherwise flip
    // scopeMode to 'some' — the explicit click above must win.
    await act(async () => { resolveFetch({ locations: { drive: SAVED, _exclude: { drive: [] } } }) })

    expect(radio(c, 'Entire connected source').getAttribute('aria-checked')).toBe('true')
    expect(radio(c, 'Specific folders').getAttribute('aria-checked')).toBe('false')
  })

  it('an untouched wizard still adopts the saved scope once the fetch resolves — the fix only guards an explicit choice', async () => {
    const { getScanLocations } = await import('./api.js')
    let resolveFetch
    getScanLocations.mockReturnValueOnce(new Promise((r) => { resolveFetch = r }))
    const c = await mount()

    // No click this time — the fetch resolving should still apply the saved default.
    await act(async () => { resolveFetch({ locations: { drive: SAVED, _exclude: { drive: [] } } }) })

    expect(radio(c, 'Specific folders').getAttribute('aria-checked')).toBe('true')
  })
})

describe('locationsKeyFor mirrors how a scan resolves its source', () => {
  // App.doScan maps 'all' to a real backend source from the tokens present. A second, different
  // answer here would seed the wizard from one source while the scan read another — the card and
  // the run then describe different estates, which is the whole failure this file is about.
  it('drive when Drive is connected', () => {
    expect(locationsKeyFor('all', { hasDrive: true, hasSP: true })).toBe('drive')
    expect(locationsKeyFor('drive', { hasDrive: true })).toBe('drive')
  })

  it('sharepoint for a SharePoint scan', () => {
    expect(locationsKeyFor('sharepoint', { hasSP: true })).toBe('sharepoint')
  })

  it('falls back to SharePoint when only Microsoft is connected', () => {
    expect(locationsKeyFor('all', { hasDrive: false, hasSP: true })).toBe('sharepoint')
  })

  it('is null when the source cannot be narrowed, so no folder step is offered', () => {
    // Offering a picker that cannot resolve a source produces an error where a missing control
    // would have produced an obvious next step — the same reasoning as Discover's token gates.
    expect(locationsKeyFor('local', { hasDrive: true })).toBe(null)
    expect(locationsKeyFor('all', {})).toBe(null)
  })
})

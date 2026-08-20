/**
 * The review step's coverage line — the number a user gets before committing to a scan.
 *
 * The feature asked for here was a live pre-scan estimate. It was NOT built, and the DOM cases
 * below are what enforce that decision rather than merely record it:
 *
 *   · under ADR 0020 a Discover run IS the listing, so an estimate is not a cheap preview of an
 *     expensive operation — it is very nearly the operation, run twice
 *   · and it would put a SECOND number for the same estate on screen, taken at a different moment
 *     under a different cap. Two numbers that can disagree, both correct, is the 2026-07-30
 *     defect: "1 document" and "8 documents" six seconds apart, reading as an estate that shrank
 *
 * So the line reports what THIS EXACT SCOPE covered last time — measured, stored, and matched on
 * the whole frozen boundary. What must not happen, all of which look fine on screen:
 *
 *   · a number captioned as this scope's that came from a run with a different boundary. The
 *     count would be real, the caption would be wrong, and nothing on the screen would say so
 *   · the line going stale when the scope changes underneath it — same failure, arrived at by
 *     editing rather than by matching
 *   · the no-history case rendering as a small number or a blank, either of which reads as
 *     "there is not much here"
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
  listFolders: vi.fn(async (parent) => (parent === 'root'
    ? { folders: [{ id: 'hr', name: 'HR' }, { id: 'fin', name: 'Finance' }] }
    : { folders: [{ id: 'arch', name: 'Archive' }] })),
  listSpFolders: vi.fn(async () => ({ drive_id: 'd', folders: [] })),
}))

const { default: ScanScopeWizard } = await import('./ScanScopeWizard.jsx')

const HR = { id: 'hr', name: 'HR' }
const FIN = { id: 'fin', name: 'Finance' }
const runOf = (over) => ({
  // Relative to "now" (~2h ago → whenLabel renders "today"/"yesterday", which the date-label test
  // below matches). This was a hardcoded '2026-08-18' that read as "yesterday" on the 19th but
  // aged into the absolute "Aug 18" on the 20th, turning whenLabel absolute and reddening the
  // whole frontend suite for everyone — a fixed calendar date in a wall-clock assertion is a
  // time bomb. Overridable per-test (the different-boundary case passes its own date).
  id: 'r1', completed_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(), source: 'drive', files: 240,
  scope: { kind: 'folder', folders: [HR] }, ...over,
})

async function mount(scans = []) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(ScanScopeWizard, {
      showStartButton: true, source: 'drive', hasDrive: true, hasSP: false,
      onStartScan: () => {}, scans,
    }))
  })
  return container
}

const btn = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent))
const chip = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent) && b.hasAttribute('aria-pressed'))
const toReview = async (c) => {
  for (let i = 0; i < 2; i++) {
    const cont = btn(c, /Continue/)
    if (!cont) break
    // eslint-disable-next-line no-await-in-loop
    await act(async () => { cont.click() })
  }
}

describe('there is still no invented pre-scan estimate', () => {
  it('says the count is determined at scan time when this scope has no history', async () => {
    const c = await mount([])
    await toReview(c)
    expect(c.textContent).toMatch(/No earlier run of this exact scope/)
    expect(c.textContent).toMatch(/determined when the scan starts/)
  })

  it('offers no "estimate" action that would list the estate a second time', async () => {
    // The control that was deliberately not built. Its absence is the decision; a test that only
    // described the decision in a comment would not notice it being added back.
    const c = await mount([])
    await toReview(c)
    expect(btn(c, /Estimate/i), 'a pre-scan estimate action appeared on the review step').toBeFalsy()
  })
})

describe('a measured number, matched on the whole boundary', () => {
  it('reports what this exact scope covered last time', async () => {
    const c = await mount([runOf({})])
    await act(async () => { chip(c, /HR/).click() })
    await toReview(c)
    expect(c.textContent).toMatch(/240 documents/)
    // WHEN it was measured, without pinning the wording to the wall clock — whenLabel returns
    // "today"/"yesterday" near the present and a date beyond it, and that boundary is covered
    // against an injected `now` in recentScopes.test.js rather than against the real one here.
    expect(c.textContent).toMatch(/this exact scope \((today|yesterday|\d+ \w+)\) covered/)
  })

  it('does NOT borrow a count from a run with a different boundary', () => {
    // THE load-bearing case, and the one that looks right: the number is real, it is just about
    // somewhere else. Checked without mounting so the scope can be stated exactly.
    return import('./scopeHistory.js').then(({ lastRunOfScope }) => {
      expect(lastRunOfScope([runOf({})], { folders: [FIN] }, 'drive')).toBe(null)
    })
  })

  it('drops the number again when the scope moves away from it', async () => {
    // A line that keeps a stale count while the scope changes underneath it is the same defect
    // reached by editing rather than by matching.
    const c = await mount([runOf({}), runOf({ id: 'r2', completed_at: '2026-08-10T10:00:00Z', files: 12, scope: { folders: [FIN] } })])
    await act(async () => { chip(c, /HR/).click() })
    await toReview(c)
    expect(c.textContent).toMatch(/240 documents/)
    // Back to step 1, switch to the Finance scope, forward again.
    await act(async () => { btn(c, /Back/).click() })
    await act(async () => { btn(c, /Back/).click() })
    await act(async () => { chip(c, /Finance/).click() })
    await toReview(c)
    expect(c.textContent).toMatch(/12 documents/)
    expect(c.textContent, 'the previous scope’s count survived the change').not.toMatch(/240 documents/)
  })

  it('says a truncated listing is a floor rather than a total', async () => {
    const c = await mount([runOf({ scope: { kind: 'folder', folders: [HR], truncated: true } })])
    await act(async () => { chip(c, /HR/).click() })
    await toReview(c)
    expect(c.textContent).toMatch(/hit its listing cap/)
    expect(c.textContent).toMatch(/the real total is higher/)
  })

  it('announces itself, because it changes as the scope does', async () => {
    const c = await mount([runOf({})])
    await toReview(c)
    const live = [...c.querySelectorAll('[aria-live="polite"]')]
      .find((n) => /exact scope/.test(n.textContent))
    expect(live, 'the coverage line is not announced').toBeTruthy()
  })
})

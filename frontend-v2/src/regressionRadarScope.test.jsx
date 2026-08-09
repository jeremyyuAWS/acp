// The regression radar, when the scan scope changed between the two scans.
//
// A score is computed over the IN-SCOPE findings, so the same unchanged document scores 60 under
// a wide scope and 75 with one criterion in scope. The backend now refuses to report that as
// improvement — but suppressing the number without saying why leaves a reader with a quiet radar
// and the conclusion that nothing changed, which is the same wrong answer arrived at from the
// other side. These tests pin the DISCLOSURE, not just the suppression.
//
// Asserted against rendered text rather than props, because "the store computes it correctly and
// nothing renders it" is the shape of every defect this area has had. Verified here rather than
// in the browser pane: the preview server roots at the shared checkout whatever worktree it is
// launched from, so a browser check of this branch would exercise code without it and pass.
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createTestRoot, unmountAll } from './testRoots.js'

// The component fetches its own diff, so the network is the seam and that is what is doubled.
// Rendering the REAL component matters here: a store that computes a correct diff nothing
// renders is precisely the defect this file exists to rule out.
// A module mock replaces the WHOLE module, so every export the render path reaches must be
// present — a regressed row renders TraceChip, which pulls three more names out of api.js. A
// partial mock fails only in the one test that renders that branch, which reads as a bug in the
// branch rather than in the double.
let NEXT_DIFF = null
vi.mock('./api.js', () => ({
  getScanDiff: () => Promise.resolve(NEXT_DIFF),
  openTraceUrl: () => '#',
  getTraceStatus: () => Promise.resolve({ available: false }),
  getScanTraces: () => Promise.resolve([]),
}))

const { default: RegressionRadar } = await import('./RegressionRadar.jsx')

const RUN = { id: 's2' }
const SCANS = [{ id: 's1' }, { id: 's2' }]      // a prior scan must exist, or the panel is null

let container, root
beforeEach(() => {
  ;({ container, root } = createTestRoot())
})
afterEach(unmountAll)

const BASE = {
  prev_at: '2026-08-01T00:00:00Z',
  cur_at: '2026-08-02T00:00:00Z',
  regressed: [],
  improved: [],
  new: [],
  removed: [],
}

async function show(diff) {
  NEXT_DIFF = { ...BASE, ...diff }
  await act(async () => {
    root.render(createElement(RegressionRadar, { run: RUN, scanList: SCANS }))
  })
  return container.textContent
}

const summary = (extra) => ({
  summary: {
    regressed: 0, improved: 0, new: 0, removed: 0, not_read: 0, incomparable: 0, ...extra,
  },
})

describe('regression radar — scope changes', () => {
  it('says the scope changed rather than going quietly empty', async () => {
    const t = await show({ scope_changed: true, ...summary({ incomparable: 2 }) })
    expect(t).toMatch(/scan scope changed/i)
  })

  it('explains WHY the scores are not compared', async () => {
    // "a score only means something against the criteria it was measured on" is the whole
    // reason; without it the message reads as a tool limitation rather than a fact about scores.
    const t = await show({ scope_changed: true, ...summary({ incomparable: 3 }) })
    expect(t).toMatch(/different set of criteria/i)
    expect(t).toMatch(/not compared/i)
  })

  it('counts files the scope excluded as NOT READ, never as removed', async () => {
    // "removed" is read as "documents left the estate". They did not; nobody opened them.
    // Merging the two is how "we assess only Word documents" becomes a support ticket.
    const t = await show({ scope_changed: true, ...summary({ not_read: 47 }) })
    expect(t).toMatch(/47 not read/i)
    expect(t).not.toMatch(/47 removed/i)
    expect(t).toMatch(/not read this time/i)
  })

  it('still shows a genuine removal alongside a not-read count', async () => {
    const t = await show({ scope_changed: true, ...summary({ removed: 2, not_read: 47 }) })
    expect(t).toMatch(/2 removed/)
    expect(t).toMatch(/47 not read/i)
  })

  it('does not claim "nothing got worse" about documents it could not compare', async () => {
    const t = await show({ scope_changed: true, ...summary({ incomparable: 5 }) })
    expect(t).toMatch(/could be compared/i)
    expect(t).not.toMatch(/no document lost conformance/i)
  })

  it('keeps the unqualified reassurance when the scope held', async () => {
    // The control. Without it the test above passes for a radar that never reassures anyone.
    const t = await show({ scope_changed: false, ...summary() })
    expect(t).toMatch(/no document lost conformance/i)
    expect(t).not.toMatch(/scan scope changed/i)
  })

  it('says nothing about scope on an ordinary diff', async () => {
    const t = await show({
      scope_changed: false,
      regressed: [{ file: 'a.docx', prev: 90, cur: 60, delta: -30, broke: [] }],
      ...summary({ regressed: 1 }),
    })
    expect(t).not.toMatch(/scan scope changed/i)
    expect(t).not.toMatch(/not read/i)
  })
})

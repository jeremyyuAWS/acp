import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { CORE_SCS } from './activeScope.js'
import { TRACKED_17 } from './ruleDetails.js'

// The criteria the default view hides: document core minus tracked. Derived, so this file
// never becomes another hand-typed copy of a list the product already states five ways.
const UNTRACKED = new Set([...CORE_SCS].filter((sc) => !TRACKED_17.has(sc)))

// The "By WCAG criterion" panel defaults to the criteria this engagement TRACKS (17, from
// api/assessment_policy.py:MOVA_TRACKED) rather than everything ACP certifies against (the
// 20-check document core). It used to default to the AGREED scope (14, from SCOPE_PRESETS);
// that changed deliberately — the 14 is what the backend GATES on and is still reported, but it
// is not what this table counts. Two properties are pinned by rendering, not by reading the
// source, because both are claims about what a customer sees:
//
//   1. the default view renders exactly the 17 tracked criteria — no more, no fewer;
//   2. the header count equals the number of rows actually on screen, in every combination of the
//      two filters, and the criteria it does not show are accounted for by a visible control.
//
// (2) is the defect this panel shipped with: the header read "20 of 20 document-core criteria
// automated" while as few as six rows were rendered beneath it. That is the same class as the
// dashboard totals fixed in #77 and #84 — a number a reader cannot reconcile against what is in
// front of them costs more confidence than an unflattering one.

const getScanTraces = vi.fn()
vi.mock('./api.js', () => ({
  getScanTraces: (...a) => getScanTraces(...a),
  openTraceUrl: () => null,
  getTraceStatus: () => Promise.resolve({ available: false }),
}))

const { RuleBreakdown } = await import('./Transparency.jsx')
const { WCAG } = await import('./wcagCatalog.js')
const LEVEL_OF = Object.fromEntries(WCAG.map((c) => [c.sc, c.level]))

// One trace row per (criterion, file), shaped like store.get_scan_traces output.
const trace = (sc, outcome, file = 'a.docx', findings = 0) => ({
  file, rule_id: sc, rule_name: `rule ${sc}`, plain_name: `plain ${sc}`,
  level: LEVEL_OF[sc] || 'A', outcome, finding_count: findings,
})

// Every document-core criterion traced, so nothing lands in "not evaluated" and the row set is
// decided purely by the scope filter.
const allCoreTraced = (outcome = 'PASS') => [...CORE_SCS].map((sc) => trace(sc, outcome))

let container, root
const mount = async () => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(RuleBreakdown, { scanId: 's1', files: [] })) })
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const btn = (t) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))

// The criterion rows for evaluated criteria — deliberately NOT `container.textContent`, which also
// carries the out-of-scope note naming the criteria that were left out.
const shownIds = () => [...container.querySelectorAll('.rulerow:not(.rulerow--manual) .rulemeta b')].map((b) => b.textContent)
const notEvaluatedIds = () => [...container.querySelectorAll('.rulerow--manual .rulemeta b')].map((b) => b.textContent)
// The header's own count line — the direct child of .rubrichdr, not the muted subtitle inside the h2.
const header = () => container.querySelector('.rubrichdr > span.muted').textContent

beforeEach(() => { getScanTraces.mockReset(); sessionStorage.clear() })
afterEach(unmountAll)   // both mount sites, inside act() — see testRoots.js

describe('RuleBreakdown defaults to the tracked criteria', () => {
  it('renders exactly the 17 tracked criteria, and none of the 3 untracked', async () => {
    getScanTraces.mockResolvedValue(allCoreTraced('PASS'))
    await mount()

    expect(shownIds().sort()).toEqual([...TRACKED_17].sort())
    expect(shownIds()).toHaveLength(17)
    for (const sc of UNTRACKED) expect(shownIds()).not.toContain(sc)
    // All 17 were traced, so nothing is left over as "not evaluated".
    expect(notEvaluatedIds()).toEqual([])
  })

  it('says how many criteria are hidden, which ones, and why — never silently', async () => {
    getScanTraces.mockResolvedValue(allCoreTraced('PASS'))
    await mount()
    const txt = container.textContent

    expect(txt).toContain('3 of the 20 document-core criteria')
    expect(txt).toContain('are not tracked for this engagement')
    expect(txt).toContain('are not counted above')
    // …and WHY, not just that they are gone: these three are viewer behaviours.
    expect(txt).toContain('viewer behaviours')
    for (const sc of UNTRACKED) expect(txt).toContain(sc)          // named, not just counted
    expect(txt).not.toMatch(/Deva/)                                 // customer name stays out of the UI
  })

  it('reports the findings the narrowing is holding back, so it cannot quietly flatter', async () => {
    // An UNSCOPED backend scan: the untracked criteria carry real recorded failures. The panel
    // still narrows to 17 — but it has to say what that costs, with the count.
    getScanTraces.mockResolvedValue([
      ...allCoreTraced('PASS').filter((t) => !UNTRACKED.has(t.rule_id)),
      ...[...UNTRACKED].map((sc) => trace(sc, 'FAIL', 'a.docx', 3)),
    ])
    await mount()

    expect(shownIds()).toHaveLength(17)
    expect(container.textContent).toContain('including 9 recorded findings')    // 3 criteria × 3
  })
})

describe('the header count is the number of rows actually shown', () => {
  it('agrees with the rendered rows, and the difference is on screen', async () => {
    // Four tracked criteria produce a result; the other thirteen ran but could not fire (N/A).
    const scoped = [...TRACKED_17]
    getScanTraces.mockResolvedValue([
      ...scoped.slice(0, 4).map((sc) => trace(sc, 'FAIL', 'a.docx', 2)),
      ...scoped.slice(4).map((sc) => trace(sc, 'SKIP')),
      ...[...UNTRACKED].map((sc) => trace(sc, 'PASS')),
    ])
    await mount()

    expect(shownIds()).toHaveLength(4)
    expect(header()).toContain('Showing 4 of 17 criteria tracked for this engagement')
    // The 13 that are not rendered are accounted for by the chip that hides them.
    expect(btn('Hiding 13 N/A')).toBeTruthy()

    // Reveal them: the header follows the rows rather than restating the denominator.
    await click(btn('Hiding 13 N/A'))
    expect(shownIds()).toHaveLength(17)
    expect(header()).toContain('Showing 17 of 17 criteria tracked for this engagement')
  })

  it('counts criteria the scan never evaluated in the section that lists them, not in the header', async () => {
    const scoped = [...TRACKED_17]
    getScanTraces.mockResolvedValue(scoped.slice(0, 9).map((sc) => trace(sc, 'PASS')))
    await mount()

    expect(shownIds()).toHaveLength(9)
    expect(header()).toContain('Showing 9 of 17 criteria tracked for this engagement')
    // rows shown (9) + N/A hidden (0) + not evaluated (8) = 17. Every term is visible.
    expect(notEvaluatedIds()).toHaveLength(8)
    expect(container.textContent).toContain('Not evaluated in this scan')
  })

  it('widening to the 20-check core moves the denominator with the rows', async () => {
    getScanTraces.mockResolvedValue(allCoreTraced('PASS'))
    await mount()
    expect(header()).toContain('Showing 17 of 17 criteria tracked for this engagement')

    await click(btn('Show all 20 document-core criteria'))
    expect(shownIds()).toHaveLength(20)
    expect(header()).toContain('Showing 20 of 20 document-core criteria')
    // Widened, there is nothing left out, so the untracked note goes away.
    expect(container.textContent).not.toContain('are not counted above')
    expect(btn('Show only the 17 tracked criteria')).toBeTruthy()
  })

  it('scopes the failure heatmap to the same list, and says which', async () => {
    // A failing criterion inside the tracked list and one outside it, same department.
    // 1.4.12 (text spacing), NOT 1.4.11 — the old fixture used 1.4.11 because it sat outside the
    // agreed 14, but it IS tracked, so under the 17 it would legitimately appear and this test
    // would have been asserting the opposite of what it means to.
    getScanTraces.mockResolvedValue([
      trace('1.1.1', 'FAIL', 'a.docx', 4),
      trace('1.4.12', 'FAIL', 'a.docx', 9),
    ])
    await act(async () => {
      ;({ container, root } = createTestRoot())
      root.render(createElement(RuleBreakdown, { scanId: 's1', files: [{ file: 'a.docx', department: 'Legal' }] }))
    })
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })

    const heat = container.querySelector('.heatmap')
    expect(heat).toBeTruthy()
    expect(heat.textContent).toContain('1.1.1')
    expect(heat.textContent).not.toContain('1.4.12')     // untracked — no row in the heatmap either
    expect(container.querySelector('.heatmaptitle').textContent)
      .toContain('within the 17 criteria tracked for this engagement')
  })
})

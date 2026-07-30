import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { SCOPE_SCS, OUT_OF_SCOPE_SCS, CORE_SCS } from './activeScope.js'

// The "By WCAG criterion" panel defaults to the criteria this engagement AGREED to assess (14,
// from the backend's SCOPE_PRESETS) rather than everything ACP certifies against (the 20-check
// document core). Two properties are pinned by rendering, not by reading the source, because both
// are claims about what a customer sees:
//
//   1. the default view renders exactly the 14 scoped criteria — no more, no fewer;
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
  container = document.createElement('div'); document.body.appendChild(container)
  root = createRoot(container)
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
afterEach(() => { root?.unmount(); container?.remove() })

describe('RuleBreakdown defaults to the agreed scope', () => {
  it('renders exactly the 14 scoped criteria, and none of the 6 outside the scope', async () => {
    getScanTraces.mockResolvedValue(allCoreTraced('PASS'))
    await mount()

    expect(shownIds().sort()).toEqual([...SCOPE_SCS].sort())
    expect(shownIds()).toHaveLength(14)
    for (const sc of OUT_OF_SCOPE_SCS) expect(shownIds()).not.toContain(sc)
    // All 14 were traced, so nothing is left over as "not evaluated".
    expect(notEvaluatedIds()).toEqual([])
  })

  it('says how many criteria are hidden, which ones, and why — never silently', async () => {
    getScanTraces.mockResolvedValue(allCoreTraced('PASS'))
    await mount()
    const txt = container.textContent

    expect(txt).toContain('6 of the 20 document-core criteria')
    expect(txt).toContain('outside this engagement’s agreed scope')
    expect(txt).toContain('are not counted above')
    for (const sc of OUT_OF_SCOPE_SCS) expect(txt).toContain(sc)   // named, not just counted
    expect(txt).not.toMatch(/Deva/)                                 // customer name stays out of the UI
  })

  it('reports the findings the narrowing is holding back, so it cannot quietly flatter', async () => {
    // An UNSCOPED backend scan: the six out-of-scope criteria carry real recorded failures. The
    // panel still narrows to 14 — but it has to say what that costs, with the count.
    getScanTraces.mockResolvedValue([
      ...allCoreTraced('PASS').filter((t) => !OUT_OF_SCOPE_SCS.has(t.rule_id)),
      ...[...OUT_OF_SCOPE_SCS].map((sc) => trace(sc, 'FAIL', 'a.docx', 3)),
    ])
    await mount()

    expect(shownIds()).toHaveLength(14)
    expect(container.textContent).toContain('including 18 recorded findings')   // 6 criteria × 3
  })
})

describe('the header count is the number of rows actually shown', () => {
  it('agrees with the rendered rows, and the difference is on screen', async () => {
    // Four scoped criteria produce a result; the other ten ran but could not fire (N/A).
    const scoped = [...SCOPE_SCS]
    getScanTraces.mockResolvedValue([
      ...scoped.slice(0, 4).map((sc) => trace(sc, 'FAIL', 'a.docx', 2)),
      ...scoped.slice(4).map((sc) => trace(sc, 'SKIP')),
      ...[...OUT_OF_SCOPE_SCS].map((sc) => trace(sc, 'PASS')),
    ])
    await mount()

    expect(shownIds()).toHaveLength(4)
    expect(header()).toContain('Showing 4 of 14 criteria in the agreed scope')
    // The 10 that are not rendered are accounted for by the chip that hides them.
    expect(btn('Hiding 10 N/A')).toBeTruthy()

    // Reveal them: the header follows the rows rather than restating the denominator.
    await click(btn('Hiding 10 N/A'))
    expect(shownIds()).toHaveLength(14)
    expect(header()).toContain('Showing 14 of 14 criteria in the agreed scope')
  })

  it('counts criteria the scan never evaluated in the section that lists them, not in the header', async () => {
    const scoped = [...SCOPE_SCS]
    getScanTraces.mockResolvedValue(scoped.slice(0, 9).map((sc) => trace(sc, 'PASS')))
    await mount()

    expect(shownIds()).toHaveLength(9)
    expect(header()).toContain('Showing 9 of 14 criteria in the agreed scope')
    // rows shown (9) + N/A hidden (0) + not evaluated (5) = 14. Every term is visible.
    expect(notEvaluatedIds()).toHaveLength(5)
    expect(container.textContent).toContain('Not evaluated in this scan')
  })

  it('widening to the 20-check core moves the denominator with the rows', async () => {
    getScanTraces.mockResolvedValue(allCoreTraced('PASS'))
    await mount()
    expect(header()).toContain('Showing 14 of 14 criteria in the agreed scope')

    await click(btn('Show all 20 in-scope criteria'))
    expect(shownIds()).toHaveLength(20)
    expect(header()).toContain('Showing 20 of 20 document-core criteria')
    // Widened, there is nothing left out, so the out-of-scope note goes away.
    expect(container.textContent).not.toContain('are not counted above')
    expect(btn('Show only the 14 in the agreed scope')).toBeTruthy()
  })

  it('scopes the failure heatmap to the same list, and says which', async () => {
    // A failing criterion inside the scope and one outside it, in the same department.
    getScanTraces.mockResolvedValue([
      trace('1.1.1', 'FAIL', 'a.docx', 4),
      trace('1.4.11', 'FAIL', 'a.docx', 9),
    ])
    await act(async () => {
      root = createRoot(container = document.body.appendChild(document.createElement('div')))
      root.render(createElement(RuleBreakdown, { scanId: 's1', files: [{ file: 'a.docx', department: 'Legal' }] }))
    })
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })

    const heat = container.querySelector('.heatmap')
    expect(heat).toBeTruthy()
    expect(heat.textContent).toContain('1.1.1')
    expect(heat.textContent).not.toContain('1.4.11')     // out of scope — no row in the heatmap either
    expect(container.querySelector('.heatmaptitle').textContent)
      .toContain('within the 14 criteria in the agreed scope')
  })
})

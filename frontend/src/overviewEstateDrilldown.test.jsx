/**
 * K1's "By document type" panel and treemap widened from the scanned subset to the whole estate.
 *
 * Only assessable formats (docx/pdf/pptx/xlsx/html) are ever opened and scored — an image or video
 * discovery merely LISTED never appears in `files`. Overview used to build "By document type" and
 * the estate-composition treemap from `files` alone, so an estate that is mostly images rendered
 * both as if it were document-only (the identical gap PR #615 closed on Discover's own "By file
 * type" panel). This fetches the paginated per-file inventory (discoveryInventory.js, the same
 * route Discover.jsx already reads for lifecycle columns) and folds in the rows scanning never
 * touched — see inventoryOnlyRows.
 *
 * DOM-level, not browser-level: this repo's preview server runs vite rooted at the SHARED checkout
 * whatever worktree you are in (CLAUDE.md), so a browser check would exercise code without this.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { collapsedToggles } from './testAccordion.js'

const here = dirname(fileURLToPath(import.meta.url))

const getScanInventory = vi.fn(async () => ({ scan_id: 's1', total: 0, offset: 0, limit: 1000, rows: [] }))
vi.mock('./api.js', async (importActual) => ({
  ...(await importActual()),
  getScanInventory: (...args) => getScanInventory(...args),
}))

const { default: Overview } = await import('./Overview.jsx')

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()); getScanInventory.mockClear() })
afterEach(unmountAll)

const RUN = { id: 's1', status: 'complete', files: 2, avg_score: 90, certifiable: 2,
              completed_at: '2026-08-21T00:00:00Z', scope: { kind: 'drive', inventory: { discovered: 2 } } }
// `type` is set explicitly — real scanned rows get it from ontology.js's annotate(), which this
// fixture bypasses. Without it every row groups under the empty-string bucket, which is a bug in
// the fixture, not in Overview.jsx (found while writing this test).
const FILES = [
  { file: 'a.docx', name: 'a.docx', type: 'DOCX', status: 'done', score: 90, issues: [] },
  { file: 'b.pdf', name: 'b.pdf', type: 'PDF', status: 'done', score: 90, issues: [] },
]

const render = async (props = {}) => {
  await act(async () => { root.render(createElement(Overview, {
    run: RUN, files: FILES, trend: [], trendDates: [], onGo: () => {}, ...props,
  })) })
  // Flush loadDiscoveryInventory's internal await + the .then(setInv) + the re-render it schedules.
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
  // "Document types & eligibility" is a disclosure that starts closed on Overview (2026-09-02 UI
  // simplification PRD), and a closed one renders no children at all. Open every accordion through
  // its real header button so the assertions below read what a user can actually see.
  for (let pass = 0; pass < 5; pass++) {
    const shut = collapsedToggles(container)
    if (!shut.length) break
    await act(async () => { shut.forEach((b) => b.click()) })
  }
  return container
}
const text = () => container.textContent
const click = async (el) => { await act(async () => { el.click() }) }

describe('the estate composition widens to files discovery listed but never scanned', () => {
  it('adds an image the estate inventory carries but no scanned row represents', async () => {
    getScanInventory.mockResolvedValue({ scan_id: 's1', total: 1, offset: 0, limit: 1000,
      rows: [{ file: 'photo.png', status: 'metadata_only', format: 'image', size_kb: 512 }] })
    await render()
    expect(text()).toContain('PNG')
  })

  it('does not duplicate a file the inventory also lists — it is already in `files`', async () => {
    getScanInventory.mockResolvedValue({ scan_id: 's1', total: 2, offset: 0, limit: 1000,
      rows: [{ file: 'a.docx', status: 'assessable', format: 'docx' },
             { file: 'b.pdf', status: 'assessable', format: 'pdf' }] })
    await render()
    // Exactly one DOCX and one PDF across the "Document types & eligibility" rows — the inventory
    // repeated both scanned files and must have added neither. The panel prints "N · P% eligible"
    // per type, so the count is the number before the separator.
    const section = container.querySelector('[data-accordion="doc-types"]')
    expect(section, 'no Document types & eligibility section').toBeTruthy()
    const labels = [...section.querySelectorAll('span')]
      .filter((el) => ['DOCX', 'PDF'].includes(el.textContent.trim()))
    expect(labels.map((el) => el.textContent.trim()).sort()).toEqual(['DOCX', 'PDF'])
    const total = labels.reduce((a, el) =>
      a + Number(el.nextElementSibling.textContent.trim().split('·')[0].replace(/,/g, '')), 0)
    expect(total).toBe(2)
  })

  // THE DRILL-THROUGH IS GONE, DELIBERATELY. Overview's clickable "By document type" bars, the
  // SegmentDrawer they opened and the EstateOnlyDrawer behind that were removed on 2026-09-02 with
  // the rest of the Overview charts (PRD "ACP Discover and Overview Simplification"). The WIDENING
  // survives — the tests above prove estate-only rows still reach the type breakdown — but nothing
  // on this screen opens a per-file drawer from it any more. Pinned so it cannot creep back
  // unnoticed; Discover's own file inventory is where a reader drills into files now.
  it('no longer offers a per-type drill-through on Overview', async () => {
    getScanInventory.mockResolvedValue({ scan_id: 's1', total: 1, offset: 0, limit: 1000,
      rows: [{ file: 'clip.mp4', status: 'metadata_only', format: 'av', size_kb: 20480, owner: 'Dana' }] })
    await render()
    expect(container.querySelector('.critrow')).toBeNull()
    expect(text()).not.toContain('Listed by discovery — not opened')
  })

  it('does not fetch the inventory at all when the scan has no id', async () => {
    await render({ run: { ...RUN, id: undefined } })
    expect(getScanInventory).not.toHaveBeenCalled()
  })
})

describe('the wiring is where it says it is', () => {
  const overview = readFileSync(join(here, 'Overview.jsx'), 'utf8')

  it('reads the paginated estate inventory and folds in what scanning never touched', () => {
    expect(overview).toMatch(/import \{ loadDiscoveryInventory, inventoryOnlyRows \} from '\.\/discoveryInventory\.js'/)
    expect(overview).toMatch(/loadDiscoveryInventory\(run\.id, getScanInventory\)/)
  })

  it('routes an estate-only row to EstateOnlyDrawer, never to FileDrawer', () => {
    expect(overview).toMatch(/import EstateOnlyDrawer from '\.\/EstateOnlyDrawer\.jsx'/)
    expect(overview).toMatch(/f\._estateOnly \? setEstOnlyFile\(f\) : setSelFile\(f\)/)
  })

  it('hands the widened estate to EstateProgressPanel, which is what renders the type breakdown', () => {
    // The panel builds its own typeMap from `estateFiles`, so this prop is the whole path by which
    // a never-opened file reaches "Document types & eligibility".
    expect(overview).toMatch(/estateFiles=\{estateFiles\}/)
    const panel = readFileSync(join(here, 'EstateProgressPanel.jsx'), 'utf8')
    expect(panel).toMatch(/for \(const f of \(estateFiles \|\| \[\]\)\)/)
  })
})

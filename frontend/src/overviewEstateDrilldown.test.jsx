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
    expect(text()).toContain('Images')
  })

  it('does not duplicate a file the inventory also lists — it is already in `files`', async () => {
    getScanInventory.mockResolvedValue({ scan_id: 's1', total: 2, offset: 0, limit: 1000,
      rows: [{ file: 'a.docx', status: 'assessable', format: 'docx' },
             { file: 'b.pdf', status: 'assessable', format: 'pdf' }] })
    await render()
    const section = container.querySelector('.balanced-coverage')
    expect(section, 'no balanced coverage section').toBeTruthy()
    const rows = [...section.querySelectorAll('.balanced-format-row')]
    expect(rows.map(row => row.querySelector('button').textContent).sort()).toEqual(['PDF', 'Word'])
    expect(rows.reduce((sum, row) => sum + Number(row.querySelector('strong').textContent), 0)).toBe(2)
  })

  it('opens an estate-only file through the balanced chart records', async () => {
    getScanInventory.mockResolvedValue({ scan_id: 's1', total: 1, offset: 0, limit: 1000,
      rows: [{ file: 'clip.mp4', status: 'metadata_only', format: 'av', size_kb: 20480, owner: 'Dana' }] })
    await render()
    const format = [...container.querySelectorAll('.balanced-format-row button')].find(button => button.textContent === 'Video / audio')
    await click(format)
    const file = container.querySelector('.balanced-evidence .balanced-link')
    expect(file.textContent).toBe('clip.mp4')
    await click(file)
    expect(text()).toContain('Listed by discovery')
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

  it('hands the recorded inventory to the balanced type breakdown', () => {
    expect(overview).toMatch(/<BalancedSummary[\s\S]{0,220}inventory=/)
    expect(overview).not.toMatch(/<EstateProgressPanel\b/)
  })
})

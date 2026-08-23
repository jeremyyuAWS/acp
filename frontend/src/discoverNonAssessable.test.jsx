/**
 * The Discover tab surfaces images, videos, and unsupported formats that discovery listed but
 * never opened for WCAG assessment — the same estate-widening the Overview tab already does
 * (overviewEstateDrilldown.test.jsx), applied to Discover's own file list.
 *
 * These files never appear in `files` (only assessable formats are ever opened and scored), so
 * without this panel the user sees a discovery count that does not match what they can browse.
 * inventoryOnlyRows() produces the rows; they are shown in a compact list and route to
 * EstateOnlyDrawer when clicked, not FileDrawer.
 *
 * DOM-level, not browser-level: this repo's preview server runs vite rooted at the SHARED checkout
 * whatever worktree you are in (CLAUDE.md), so a browser check would exercise code without this.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const getScanInventory = vi.fn(async () => ({ scan_id: 's1', total: 0, offset: 0, limit: 1000, rows: [] }))

vi.mock('./api.js', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    getScanInventory: (...args) => getScanInventory(...args),
    // Stub other side-effectful routes Discover touches so the tests do not make real network calls.
    listScanDecisions: async () => [],
    overrideLifecycleRecommendation: async () => {},
  }
})

const { default: Discover } = await import('./Discover.jsx')

let container, root
beforeEach(() => {
  ;({ container, root } = createTestRoot())
  getScanInventory.mockClear()
  getScanInventory.mockResolvedValue({ scan_id: 's1', total: 0, offset: 0, limit: 1000, rows: [] })
})
afterEach(unmountAll)

const FILES = [
  { file: 'report.docx', type: 'DOCX', tags: [], issues: [], department: 'HR', sourceName: 'SharePoint' },
]

const render = async (props = {}) => {
  await act(async () => {
    root.render(createElement(Discover, {
      sources: [{ name: 'SharePoint' }],
      files: FILES,
      busy: false,
      onScan: () => {},
      onAdvance: () => {},
      scanId: 's1',
      ...props,
    }))
  })
  // Flush loadDiscoveryInventory's internal await + the .then(setInv) + the re-render it schedules.
  for (let k = 0; k < 6; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
  return container
}
const text = () => container.textContent
const click = async (el) => { await act(async () => { el.click() }) }

describe('non-assessable files panel', () => {
  it('is absent when the inventory read has not completed', async () => {
    // The panel must not appear during a pending read — the count would be 0 and read as "no such
    // files" rather than "we do not know yet".
    getScanInventory.mockReturnValue(new Promise(() => {}))
    await render()
    expect(text()).not.toContain('images, videos, and unsupported formats')
  })

  it('is absent when the inventory returns no non-assessable rows', async () => {
    // Only the assessable file in FILES is in the inventory — nothing to surface.
    getScanInventory.mockResolvedValue({
      scan_id: 's1', total: 1, offset: 0, limit: 1000,
      rows: [{ file: 'report.docx', status: 'assessable', format: 'docx' }],
    })
    await render()
    expect(text()).not.toContain('images, videos, and unsupported formats')
  })

  it('lists an image the inventory carries but no scanned row represents', async () => {
    getScanInventory.mockResolvedValue({
      scan_id: 's1', total: 2, offset: 0, limit: 1000,
      rows: [
        { file: 'report.docx', status: 'assessable', format: 'docx' },
        { file: 'logo.png', status: 'metadata_only', format: 'image', size_kb: 256 },
      ],
    })
    await render()
    expect(text()).toContain('images, videos, and unsupported formats')
    expect(text()).toContain('logo.png')
    expect(text()).toContain('1')   // count badge
  })

  it('clicking a non-assessable file opens EstateOnlyDrawer, not FileDrawer', async () => {
    getScanInventory.mockResolvedValue({
      scan_id: 's1', total: 2, offset: 0, limit: 1000,
      rows: [
        { file: 'report.docx', status: 'assessable', format: 'docx' },
        { file: 'clip.mp4', status: 'metadata_only', format: 'av', size_kb: 40960, owner: 'Sam' },
      ],
    })
    await render()
    const btn = [...container.querySelectorAll('button')].find((b) => b.textContent.includes('clip.mp4'))
    expect(btn).toBeTruthy()
    await click(btn)
    // EstateOnlyDrawer says this, FileDrawer does not.
    expect(text()).toContain('Listed by discovery — not opened')
    expect(text()).toContain('ACP never opened it')
  })

  it('does not show excluded rows (ACP internal output, not user content)', async () => {
    getScanInventory.mockResolvedValue({
      scan_id: 's1', total: 2, offset: 0, limit: 1000,
      rows: [
        { file: 'report.docx', status: 'assessable', format: 'docx' },
        { file: '.acp-cache/meta.json', status: 'excluded', format: 'json' },
      ],
    })
    await render()
    expect(text()).not.toContain('.acp-cache')
    expect(text()).not.toContain('images, videos, and unsupported formats')
  })
})

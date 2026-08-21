import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// K1 · Estate composition treemap. Pins: area-by-count renders every type, the "by total pages"
// toggle is offered ONLY when some file actually carries a page count (never a toggle into an
// all-absent chart), clicking a tile fires onPick with that type's label, and — since no real
// per-type classification signal exists today (see the #603 fix this mirrors) — the Coverage
// column always reads "not measured", never a guessed percentage.

const { default: EstateTreemap } = await import('./EstateTreemap.jsx')

const BY_COUNT = [
  { label: 'WORD', value: 35 }, { label: 'PDF', value: 33 }, { label: 'EXCEL', value: 20 },
]

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(EstateTreemap, { byCount: BY_COUNT, ...props })) })
  return container
}
afterEach(unmountAll)

describe('EstateTreemap', () => {
  it('renders every type from byCount, ranked by size', async () => {
    const c = await mount()
    const rows = [...c.querySelectorAll('table tbody tr')].map((r) => r.textContent)
    expect(rows.length).toBe(3)
    expect(rows[0]).toContain('WORD')   // largest first
    expect(rows[2]).toContain('EXCEL')  // smallest last
  })

  it('never claims a coverage percentage — "not measured" on every row', async () => {
    const c = await mount()
    const cells = [...c.querySelectorAll('table tbody tr')].map((r) => r.textContent)
    for (const row of cells) expect(row).toContain('not measured')
    expect(c.textContent).not.toMatch(/coverage[^a-z]*\d+%/i)
  })

  it('does not offer the "by total pages" toggle when nothing has a page count', async () => {
    const c = await mount({ byPages: null })
    const btns = [...c.querySelectorAll('button')].map((b) => b.textContent)
    expect(btns).not.toContain('By total pages')
  })

  it('offers the toggle once real page data exists, and switching changes the ranking', async () => {
    // PDF has far more total pages than WORD despite fewer files — a real toggle must re-sort.
    const byPages = [{ label: 'WORD', value: 40 }, { label: 'PDF', value: 900 }, { label: 'EXCEL', value: 20 }]
    const c = await mount({ byPages })
    const toggle = [...c.querySelectorAll('button')].find((b) => b.textContent === 'By total pages')
    expect(toggle).toBeTruthy()
    await act(async () => { toggle.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    const rows = [...c.querySelectorAll('table tbody tr')].map((r) => r.textContent)
    expect(rows[0]).toContain('PDF')   // now ranked by pages, PDF leads
  })

  it('ignores a byPages array that is all zero — same as no page data at all', async () => {
    const c = await mount({ byPages: [{ label: 'WORD', value: 0 }, { label: 'PDF', value: 0 }] })
    const btns = [...c.querySelectorAll('button')].map((b) => b.textContent)
    expect(btns).not.toContain('By total pages')
  })

  it('fires onPick with the type label when a tile is clicked', async () => {
    let picked = null
    const c = await mount({ onPick: (label) => { picked = label } })
    const g = c.querySelector('svg g')
    await act(async () => { g.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(picked).toBe('WORD')   // the largest slice is laid out first
  })

  it('shows an honest empty state with nothing to compose', async () => {
    const c = await mount({ byCount: [] })
    expect(c.textContent).toContain('No documents to compose yet')
  })
})

import { describe, it, expect, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: OverviewPreviewCard } = await import('./OverviewPreviewCard.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(OverviewPreviewCard, props)) })
  return container
}
afterEach(unmountAll)

const PREVIEW = {
  estate: { discovered: 12408, assessable: 9000 },
  documents: { assessed: 4500, certifiable: 1200, excluded: 300, unassessable: 4200 },
  score: { avg: 71.4 },
  freshness: { completed_at: '2026-08-20T16:04:00Z' },
}

describe('OverviewPreviewCard', () => {
  it('renders nothing when there is no preview yet', async () => {
    const c = await mount({ preview: null })
    expect(c.textContent).toBe('')
  })

  it('renders the aggregate counts from the cached snapshot', async () => {
    const c = await mount({ preview: PREVIEW })
    expect(c.textContent).toContain('12,408')
    expect(c.textContent).toContain('1,200')
    expect(c.textContent).toContain('71/100')
  })

  it('shows the assessed count with its percentage of the discovered estate', async () => {
    const c = await mount({ preview: PREVIEW })
    // 4500 / 12408 ≈ 36%
    expect(c.textContent).toContain('4,500 (36%)')
  })

  it('renders an em dash for counts the snapshot does not have', async () => {
    const c = await mount({ preview: { estate: {}, documents: {}, score: {} } })
    expect(c.textContent).toContain('—')
  })

  it('does not show a percentage when nothing has been discovered yet', async () => {
    const c = await mount({ preview: { estate: { discovered: 0 }, documents: {}, score: {} } })
    expect(c.textContent).not.toMatch(/\d+%/)
  })

  it('does not show a percentage when the estate has counts but assessed is not in the snapshot yet', async () => {
    // The exact shape GET /workspace/bootstrap sends on the very first render — estate.discovered
    // present, documents.assessed absent. "— (0%)" would misread as "assessed nothing yet" rather
    // than "not measured yet".
    const c = await mount({ preview: { estate: { discovered: 3 }, documents: { certifiable: 2 }, score: {} } })
    expect(c.textContent).not.toMatch(/\d+%/)
    expect(c.textContent).toContain('—')
  })

  it('shows a "loading full detail" indicator', async () => {
    const c = await mount({ preview: PREVIEW })
    expect(c.textContent).toMatch(/loading full detail/)
  })

  it('marks the card aria-busy so assistive tech knows more is coming', async () => {
    const c = await mount({ preview: PREVIEW })
    expect(c.querySelector('[aria-busy="true"]')).toBeTruthy()
  })

  it('shows a last-updated stamp when freshness data is available', async () => {
    const c = await mount({ preview: PREVIEW })
    expect(c.textContent).toMatch(/Last updated/)
  })

  it('omits the last-updated line when no freshness timestamp is available', async () => {
    const c = await mount({ preview: { estate: {}, documents: {}, score: {}, freshness: {} } })
    expect(c.textContent).not.toMatch(/Last updated/)
  })

  it('falls back through freshness fields when completed_at is missing', async () => {
    const c = await mount({ preview: { estate: {}, documents: {}, score: {},
      freshness: { discovered_at: '2026-08-19T10:00:00Z' } } })
    expect(c.textContent).toMatch(/Last updated/)
  })
})

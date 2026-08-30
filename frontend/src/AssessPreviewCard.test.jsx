import { describe, it, expect, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: AssessPreviewCard } = await import('./AssessPreviewCard.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(AssessPreviewCard, props)) })
  return container
}
afterEach(unmountAll)

const PREVIEW = {
  estate: { discovered: 12408, assessable: 9000 },
  documents: { assessed: 4500, certifiable: 1200, excluded: 300, unassessable: 4200 },
  score: { avg: 71.4 },
  severity_distribution: { CRITICAL: 12, SERIOUS: 40, MODERATE: 0, MINOR: 8 },
}

describe('AssessPreviewCard', () => {
  it('renders nothing when there is no preview yet', async () => {
    const c = await mount({ preview: null })
    expect(c.textContent).toBe('')
  })

  it('renders the aggregate counts from the cached snapshot', async () => {
    const c = await mount({ preview: PREVIEW })
    expect(c.textContent).toContain('1,200')
    expect(c.textContent).toContain('71/100')
  })

  it('shows the assessed count with its percentage of the assessable estate', async () => {
    const c = await mount({ preview: PREVIEW })
    // 4500 / 9000 = 50%
    expect(c.textContent).toContain('4,500 (50%)')
  })

  it('renders an em dash for counts the snapshot does not have', async () => {
    const c = await mount({ preview: { estate: {}, documents: {}, score: {} } })
    expect(c.textContent).toContain('—')
  })

  it('does not show a percentage when the assessable estate is unknown', async () => {
    const c = await mount({ preview: { estate: {}, documents: { assessed: 10 }, score: {} } })
    expect(c.textContent).not.toMatch(/\d+%/)
  })

  it('lists only the severities present with a nonzero count', async () => {
    const c = await mount({ preview: PREVIEW })
    expect(c.textContent).toContain('12 critical')
    expect(c.textContent).toContain('40 serious')
    expect(c.textContent).toContain('8 minor')
    expect(c.textContent).not.toContain('moderate')
  })

  it('omits the severity row entirely when there is nothing to show', async () => {
    const c = await mount({ preview: { estate: {}, documents: {}, score: {}, severity_distribution: {} } })
    expect(c.textContent).not.toMatch(/critical|serious|moderate|minor/)
  })

  it('shows a "loading full detail" indicator', async () => {
    const c = await mount({ preview: PREVIEW })
    expect(c.textContent).toMatch(/loading full detail/)
  })

  it('says setup and results are not available yet', async () => {
    const c = await mount({ preview: PREVIEW })
    expect(c.textContent).toMatch(/Setup and per-document results become available/)
  })

  it('marks the card aria-busy so assistive tech knows more is coming', async () => {
    const c = await mount({ preview: PREVIEW })
    expect(c.querySelector('[aria-busy="true"]')).toBeTruthy()
  })

  it('never renders a run button or drill-in control — this is read-only', async () => {
    const c = await mount({ preview: PREVIEW })
    expect(c.querySelectorAll('button').length).toBe(0)
  })
})

import { describe, it, expect, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: MonitorPreviewCard } = await import('./MonitorPreviewCard.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(MonitorPreviewCard, props)) })
  return container
}
afterEach(unmountAll)

const PREVIEW = {
  estate: { discovered: 12408, assessable: 9000 },
  documents: { assessed: 4500, certifiable: 1200, excluded: 300, unassessable: 4200 },
  score: { avg: 71.4 },
  severity_distribution: { CRITICAL: 12, SERIOUS: 40, MODERATE: 0, MINOR: 8 },
}

describe('MonitorPreviewCard', () => {
  it('renders nothing when there is no preview yet', async () => {
    const c = await mount({ preview: null })
    expect(c.textContent).toBe('')
  })

  it('renders the compliance numbers from the cached snapshot', async () => {
    const c = await mount({ preview: PREVIEW })
    expect(c.textContent).toContain('71/100')
    expect(c.textContent).toContain('4,500')
    expect(c.textContent).toContain('1,200')
  })

  it('renders an em dash for counts the snapshot does not have', async () => {
    const c = await mount({ preview: { estate: {}, documents: {}, score: {} } })
    expect(c.textContent).toContain('—')
  })

  it('lists only the severities present with a nonzero count', async () => {
    const c = await mount({ preview: PREVIEW })
    expect(c.textContent).toContain('12 critical')
    expect(c.textContent).toContain('40 serious')
    expect(c.textContent).toContain('8 minor')
    expect(c.textContent).not.toContain('moderate')
  })

  it('shows a "loading full detail" indicator', async () => {
    const c = await mount({ preview: PREVIEW })
    expect(c.textContent).toMatch(/loading full detail/)
  })

  it('says source watch and drift tracking are not available yet', async () => {
    const c = await mount({ preview: PREVIEW })
    expect(c.textContent).toMatch(/Source watch, the event stream, and drift tracking/)
  })

  it('marks the card aria-busy so assistive tech knows more is coming', async () => {
    const c = await mount({ preview: PREVIEW })
    expect(c.querySelector('[aria-busy="true"]')).toBeTruthy()
  })

  it('never renders a button — this is read-only', async () => {
    const c = await mount({ preview: PREVIEW })
    expect(c.querySelectorAll('button').length).toBe(0)
  })
})

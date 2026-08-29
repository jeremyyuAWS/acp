// The Discover completion card's "See what's changed since your last scan of this source" link
// (DiscoverCompleteSummary.jsx) needs a real source key to redirect with — Discover.jsx is the
// only place that has `run.source`, so it computes the click handler and passes it down. These
// tests exercise that computation directly against Discover.jsx: which key `onOpenSource` gets
// called with, and the one case (`run.source === 'all'`) where the link must not render at all,
// because Integrations' sourceKeys() matching (sourceRedirectWiring.test.jsx) cannot resolve
// "all" to a single source card and a link to a dead end is worse than no link.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: Discover } = await import('./Discover.jsx')

const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => {
    root.render(createElement(Discover, { sources: [], files: [], busy: false, onScan: () => {}, ...props }))
  })
  return container
}
afterEach(unmountAll)

const doneRun = (extra = {}) => ({ id: 's1', status: 'discovered', discovered_at: '2026-08-29T04:00:00Z', ...extra })
const findLink = (c) => [...c.querySelectorAll('button')].find((b) => /See what.s changed/.test(b.textContent))

describe('the completion card\'s source-history redirect', () => {
  it('calls onOpenSource with the run\'s own source string', async () => {
    const onOpenSource = vi.fn()
    const c = await mount({
      files: [], scope: { kind: 'drive', inventory: { discovered: 0 } },
      run: doneRun({ source: 'drive' }), onOpenSource,
    })
    const link = findLink(c)
    expect(link).toBeTruthy()
    await act(async () => { link.click() })
    expect(onOpenSource).toHaveBeenCalledWith('drive')
  })

  it('omits the link when the caller supplied no onOpenSource handler', async () => {
    const c = await mount({
      files: [], scope: { kind: 'drive', inventory: { discovered: 0 } }, run: doneRun({ source: 'drive' }),
    })
    expect(findLink(c)).toBeUndefined()
  })

  it('omits the link for a whole-Drive/multi-source scan (run.source === "all") — sourceKeys() '
     + 'matching cannot resolve "all" to one source card', async () => {
    const c = await mount({
      files: [], scope: { kind: 'drive', inventory: { discovered: 0 } },
      run: doneRun({ source: 'all' }), onOpenSource: vi.fn(),
    })
    expect(findLink(c)).toBeUndefined()
  })

  it('omits the link when the run itself carries no source', async () => {
    const c = await mount({
      files: [], scope: { kind: 'drive', inventory: { discovered: 0 } },
      run: doneRun({ source: undefined }), onOpenSource: vi.fn(),
    })
    expect(findLink(c)).toBeUndefined()
  })
})

// The Discover completion card's "See what's changed since your last scan of this source" link
// lived on DiscoverCompleteSummary, which was UNMOUNTED on 2026-09-02 (PRD "ACP Discover and
// Overview Simplification"). The link went with it: Discover reports what a scan found, and the
// source's own history is read on Sources, where the card the link pointed at already lives.
//
// This file pins the removal rather than being deleted, and every case below asserts the ABSENCE
// against a mount that would otherwise have rendered the link — the negative assertions on their
// own are all satisfied by a component that failed to render at all, which is the shape that makes
// a removal test worthless. The first case establishes the panel is on screen before the rest read
// anything into its silence.
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

describe('the source-history redirect is intentionally NOT on Discover', () => {
  it('renders the completion panel, and no redirect link inside it', async () => {
    const onOpenSource = vi.fn()
    const c = await mount({
      files: [], scope: { kind: 'drive', inventory: { discovered: 0 } },
      run: doneRun({ source: 'drive' }), onOpenSource,
    })
    // The panel this link used to sit in IS on screen — so its absence below is the removal.
    expect(c.textContent).toContain('Estate overview')
    expect(findLink(c)).toBeUndefined()
    expect(onOpenSource).not.toHaveBeenCalled()
  })

  it('does not call onOpenSource from anywhere else on the screen either', async () => {
    const onOpenSource = vi.fn()
    const c = await mount({
      files: [], scope: { kind: 'drive', inventory: { discovered: 0 } },
      run: doneRun({ source: 'drive' }), onOpenSource,
    })
    for (const b of [...c.querySelectorAll('button')]) {
      if (/See what.s changed/.test(b.textContent)) throw new Error('the redirect link is back')
    }
    expect(onOpenSource).not.toHaveBeenCalled()
  })

  it('keeps the "all" case moot — there is no link to resolve to a source card', async () => {
    // Integrations' sourceKeys() matching (sourceRedirectWiring.test.jsx) cannot resolve "all" to
    // one source card, which is why the link had to hide itself for a multi-source scan. Nothing
    // to hide now; recorded so a restored link restores the guard with it.
    const c = await mount({
      files: [], scope: { kind: 'drive', inventory: { discovered: 0 } },
      run: doneRun({ source: 'all' }), onOpenSource: vi.fn(),
    })
    expect(c.textContent).toContain('Estate overview')
    expect(findLink(c)).toBeUndefined()
  })
})

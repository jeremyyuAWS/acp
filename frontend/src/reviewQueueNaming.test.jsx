import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'

// Redesign spec R4 §3 — "AI Work Inbox" describes how the work was GENERATED, not what the user
// must do with it. The queue is now "Review queue"; whether a finding carries an AI draft is an
// attribute OF THAT FINDING, shown on its card, not the identity of the queue it sits in.
//
// WHY THIS TEST EXISTS AT ALL. The old name was on screen in five places across four components
// and in ~25 comments, and NOTHING asserted any of them — the rename could half-land, or drift
// back one component at a time, with a green suite either way. The spec called it out as
// "coordinated work, not just the section header", which is exactly the shape of change that
// needs a guard rather than care.
//
// Two lanes, deliberately. The DOM case proves the string a user actually reads; the source
// sweep proves nobody LEFT one behind — including in a file this test's author never opened.
// Neither substitutes for the other: a DOM test can only assert the surfaces it thought to
// mount, and a source sweep cannot tell a rendered heading from a comment.

vi.mock('./api.js', () => ({ openTraceUrl: () => {} }))

const { default: ReviewCenter } = await import('./ReviewCenter.jsx')

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

afterEach(() => unmountAll())

describe('the review queue is named for the work, not for its generator', () => {
  it('names the full-screen queue "Review queue" — heading and accessible name alike', () => {
    const { root, container } = createTestRoot()
    act(() => root.render(createElement(ReviewCenter, {
      items: [], onAct: () => {}, onClose: () => {}, onRefresh: () => {}, error: null,
    })))

    const dialog = container.querySelector('[role="dialog"]')
    expect(dialog, 'the Review Center should render a dialog').toBeTruthy()
    // The accessible name matters as much as the visible one: a screen-reader user hears this
    // string as the name of the whole surface, and it was the last place the old term would
    // have survived unnoticed.
    expect(dialog.getAttribute('aria-label')).toBe('Review queue')
    expect(container.querySelector('.rc-title').textContent).toContain('Review queue')
    expect(container.textContent).not.toContain('AI Work Inbox')
  })

  it('renames the Remediate section header', () => {
    // Source-level, matching remediateCollapse.test.js: Remediate mounts a page's worth of
    // dependencies, and what is asserted here is a literal in the JSX, not behaviour.
    const r = read('Remediate.jsx')
    expect(r).toMatch(/<h2 style=\{\{ margin: 0 \}\}>Review queue<\/h2>/)
    // The ProgressRail's `label: 'Review queue'` step was asserted here too, until R4 item 1
    // deleted the rail (see remediateNavigation.test.jsx). Dropped rather than loosened: the
    // line it pinned does not exist, so any weakened form of it would pass vacuously. The
    // sweep below still covers the whole file for the retired name.
  })

  it('renames the bell and the Publish hand-off that points at it', () => {
    const bell = read('HitlBell.jsx')
    expect(bell).toContain('`Review queue — ${pending.length} pending`')
    expect(bell).toContain('<b>Review queue</b>')
    // Publish tells a blocked operator where to go. If it still named the old section the
    // instruction would point at a heading that no longer exists anywhere in the product.
    expect(read('Publish.jsx')).toContain('Remediate → step 3 · Review queue')
    expect(read('Upload.jsx')).toContain('>Review queue →</button>')
  })

  it('leaves the old term nowhere in the SPA — comments and CSS included', () => {
    // The sweep. A partial rename is the failure mode here: five user-visible strings across
    // four components, plus the comments an engineer reads next time. Leaving the maintainer's
    // copy of the term behind is how a rename quietly half-reverts.
    const SELF = 'reviewQueueNaming.test.jsx'   // the guard has to name what it forbids
    const files = readdirSync(HERE, { recursive: true })
      .map(String)
      .filter((f) => /\.(jsx?|css)$/.test(f) && f !== SELF)
    // Prove the sweep is actually reading files. An empty or mis-globbed list would satisfy
    // the assertion below by looking at nothing — a check that cannot fail is worthless.
    expect(files.length).toBeGreaterThan(100)
    expect(files.filter((f) => read(f).includes('AI Work Inbox')),
           'these still carry the retired name').toEqual([])
  })
})

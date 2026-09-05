/**
 * The Access restricted screen (PRD §10) — what it says, and the two things it must not say.
 *
 * A CAVEAT WORTH READING BEFORE TRUSTING THIS FILE. §10 asks for this screen on "a direct link to
 * a restricted tab", and ACP has no per-tab links: `view` is React state in App.jsx with no URL
 * routing at all (verified by grep — no location.hash, no searchParams, no history.pushState). So
 * the deep-link case §10 describes cannot arise today. What CAN reach this screen is a role
 * changed under a live session (App re-reads access on focus, per §9) and the app's own internal
 * navigations to a tab the role hides. It is tested here as a component because that is where its
 * behaviour is, and the App-level wiring is asserted in accessNavigation.test.jsx.
 *
 * Recorded rather than quietly satisfied: an acceptance criterion that cannot be exercised is not
 * a passing one, and "hidden tabs cannot be opened through direct URLs" (§16) is trivially true
 * here only because there are no URLs to try.
 */
import { describe, it, expect, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import AccessRestricted from './AccessRestricted.jsx'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))

const TABS = [
  ['overview', 'Overview', 'at a glance', 0],
  ['remediate', 'Remediate', 'fix issues', 3],
  ['liveops', 'Live Operations', 'Azure traffic', 0],
]

const reviewer = {
  enforced: true, role: { id: 'remediation-reviewer', name: 'Remediation Reviewer' },
  tabs: { overview: 'view', remediate: 'operate', liveops: 'hidden' }, capabilities: [],
}
const nothing = {
  enforced: true, role: null,
  tabs: { overview: 'hidden', remediate: 'hidden', liveops: 'hidden' }, capabilities: [],
}
// Someone who arrived through just-in-time roster creation on a deployment that configures no
// default role. Structurally identical to `nothing` above except for the server's `pending` flag,
// which is the whole point: the two states are indistinguishable from the tabs alone.
const pending = { ...nothing, pending: true }

async function mount(props) {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(AccessRestricted, { tabs: TABS, ...props })) })
  return container
}

afterEach(() => unmountAll())

describe('it says what is missing', () => {
  it('names the tab and the role, so the user knows what to ask for', async () => {
    const c = await mount({ access: reviewer, tabKey: 'liveops', label: 'Live Operations',
                            onGo: vi.fn() })
    expect(c.textContent).toContain('Access restricted')
    expect(c.textContent).toContain('Live Operations')
    expect(c.textContent).toContain('Remediation Reviewer')
  })

  it('says so plainly when the user has no role at all', async () => {
    const c = await mount({ access: nothing, tabKey: 'remediate', label: 'Remediate',
                            onGo: vi.fn() })
    expect(c.textContent).toMatch(/no workspace role/i)
  })
})

describe('it does not leak what is behind the tab', () => {
  it('carries no counts and no document or finding language', async () => {
    // §10: "identifies the missing permission without exposing protected data." The helpful
    // version — "Remediate · 3 documents await your review" — tells somebody without access both
    // that the tab exists and how much is in it.
    const c = await mount({ access: reviewer, tabKey: 'liveops', label: 'Live Operations',
                            onGo: vi.fn() })
    expect(c.textContent).not.toMatch(/\d/)
    expect(c.textContent.toLowerCase()).not.toContain('document')
    expect(c.textContent.toLowerCase()).not.toContain('finding')
  })
})

describe('it offers a way on, when there is one', () => {
  it('sends the user to the first tab they do have', async () => {
    const onGo = vi.fn()
    const c = await mount({ access: reviewer, tabKey: 'liveops', label: 'Live Operations', onGo })
    const btn = [...c.querySelectorAll('button')].find((b) => /Go to/.test(b.textContent))
    expect(btn.textContent).toContain('Overview')
    await act(async () => { btn.click() })
    expect(onGo).toHaveBeenCalledWith('overview')
  })

  it('offers no button at all when nothing is open to them', async () => {
    // A button here would send them to a tab that is equally closed, which bounces them straight
    // back — a loop produced by code that looks like a sensible fallback. Saying what to do
    // instead is the honest answer.
    const c = await mount({ access: nothing, tabKey: 'remediate', label: 'Remediate',
                            onGo: vi.fn() })
    expect([...c.querySelectorAll('button')].filter((b) => /Go to/.test(b.textContent))).toHaveLength(0)
    expect(c.textContent).toMatch(/administrator can assign you a role/i)
  })
})

describe('it is announced and it is styled', () => {
  it('is a polite live region — the tab body changed under the user', async () => {
    const c = await mount({ access: reviewer, tabKey: 'liveops', label: 'Live Operations',
                            onGo: vi.fn() })
    const region = c.querySelector('[role="status"]')
    expect(region).toBeTruthy()
    expect(region.getAttribute('aria-live')).toBe('polite')
  })

  it('every class it renders has a rule in styles.css', async () => {
    // A className with no rule renders as nothing and looks like a layout bug nobody wrote.
    const css = readFileSync(join(here, 'styles.css'), 'utf8')
    const src = readFileSync(join(here, 'AccessRestricted.jsx'), 'utf8')
    const used = new Set([...src.matchAll(/access-restricted[a-z-]*/g)].map((m) => m[0]))
    expect([...used].filter((cls) => !css.includes(`.${cls}`))).toEqual([])
    expect(used.size).toBeGreaterThan(2)
  })
})

describe('access pending is not access restricted', () => {
  // Owner decision, 2026-09-05: "If no default is configured, show 'Access pending' instead of a
  // broken or empty application." A person held in the queue was never denied a permission — they
  // are waiting for somebody to choose one — and a screen headed "Access restricted" naming a role
  // they do not have sends them to argue about the wrong thing with the wrong person.
  it('says pending, not restricted', async () => {
    const c = await mount({ access: pending, tabKey: 'remediate', label: 'Remediate',
                            onGo: vi.fn() })
    expect(c.textContent).toContain('Access pending')
    expect(c.textContent).not.toContain('Access restricted')
  })

  it('tells them what will change it, and that signing in again will not', async () => {
    // Without the second half they retry the login, decide the product is broken, and report it
    // as a bug — which is exactly the outcome this screen exists to replace.
    const c = await mount({ access: pending, tabKey: 'remediate', label: 'Remediate',
                            onGo: vi.fn() })
    expect(c.textContent).toMatch(/administrator/i)
    expect(c.textContent).toMatch(/signing in again will not/i)
  })

  it('offers no way on, because there is none', async () => {
    const c = await mount({ access: pending, tabKey: 'remediate', label: 'Remediate',
                            onGo: vi.fn() })
    expect([...c.querySelectorAll('button')]).toHaveLength(0)
  })

  it('THE CONTROL: an identical payload without the flag still reads as restricted', async () => {
    // Without this, "pending renders the pending screen" is satisfiable by rendering it for
    // everyone with no role — including a suspended user, whose access was deliberately withdrawn
    // and who must not be told they are awaiting approval.
    const c = await mount({ access: nothing, tabKey: 'remediate', label: 'Remediate',
                            onGo: vi.fn() })
    expect(c.textContent).toContain('Access restricted')
    expect(c.textContent).not.toContain('Access pending')
  })
})

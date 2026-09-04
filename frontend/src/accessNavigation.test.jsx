/**
 * Role-aware navigation, in the real App — the tabs that render, their numbering, and what
 * happens when a role changes under a live session.
 *
 * DOM-LEVEL, NOT BROWSER-LEVEL, and not by choice: this repo's preview server runs vite rooted at
 * the SHARED checkout whatever worktree you are in (CLAUDE.md), so a screenshot would be evidence
 * about `main` rather than about this branch.
 *
 * WHAT IS ACTUALLY UNDER TEST HERE is the wiring, not the decision — `access.test.js` owns the
 * decision table and can be exhaustive about it without mounting anything. What only shows up in
 * the real App is whether the payload reaches the nav at all, whether the workflow renumbers, and
 * whether an absent payload leaves today's product untouched. That last one is the regression
 * this whole slice could cause and none of the unit tests would catch: every existing session,
 * every SIM session, and every signed-out shell has no access payload.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.__BUILD_TIME__ = '2026-08-01T00:00:00.000Z'
globalThis.__BUILD_VERSION__ = '2026.8.1'

// The access payload the server would return. Reassigned per test BEFORE mounting; bootstrap
// reads it once, and getMyAccess re-reads it on focus (PRD §9).
let ACCESS = null
const getMyAccess = vi.fn(async () => ACCESS)

vi.mock('./api.js', async (importActual) => {
  const actual = await importActual()
  return {
    ...actual,
    getConfig: vi.fn(async () => ({ auth: 'demo' })),
    getRubric: vi.fn(async () => ({ target: 'WCAG 2.1 AA', hash: 'abcdef0123' })),
    getSources: vi.fn(async () => []),
    listScans: vi.fn(async () => []),
    getActiveScan: vi.fn(async () => null),
    getSettings: vi.fn(async () => ({ scan_scope: '' })),
    getDecisions: vi.fn(async () => ({})),
    getMyAccess,
    // The one call the navigation actually depends on. SIM's own bootstrap carries no `access`,
    // which is exactly the "not told" case the last describe block asserts is harmless.
    getWorkspaceBootstrap: vi.fn(async () => ({
      me: { email: 'rev@hosp.org', is_admin: false, is_scope_owner: false, access: ACCESS },
      scan_id: null, scan_status: null, revision: 0, overview: null, scans: [], active_job: {},
    })),
  }
})

const { default: App } = await import('./App.jsx')

afterEach(() => { unmountAll(); sessionStorage.clear(); ACCESS = null })
beforeEach(() => { sessionStorage.clear(); getMyAccess.mockClear() })

const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve() }) }
const click = async (el) => { await act(async () => { el.click() }); await flush() }
const byText = (c, sel, re) => [...c.querySelectorAll(sel)].find((e) => re.test(e.textContent))
const tabs = (c) => [...c.querySelectorAll('[role="tab"]')]
const tabNamed = (c, label) => byText(c, '[role="tab"]', new RegExp(label))
const tabLabels = (c) => tabs(c).map((t) => t.querySelector('.tablbl')?.textContent?.trim())

/** Every governed tab at one level, as api/workspace_rbac.tabs_payload returns it. */
const allTabs = (level) => Object.fromEntries(
  ['overview', 'integrations', 'discover', 'assess', 'remediate', 'publish', 'monitor',
   'liveops', 'analytics', 'settings'].map((k) => [k, level]))

async function signIn() {
  const { container: c, root } = createTestRoot()
  await act(async () => { root.render(createElement(App)) })
  await flush()
  await click(byText(c, 'button', /Sign in with SSO/))
  return c
}

// ── the regression this slice could cause ─────────────────────────────────────

describe('a session with no access payload is untouched', () => {
  it('renders the same tabs it always did', async () => {
    // SIM, signed out, an older API, or the first render before bootstrap answers. If this
    // narrowed the navigation, every existing user would lose surfaces on deploy day — and the
    // server would still be letting them through, so nothing would be protected by it either.
    ACCESS = null
    const c = await signIn()
    expect(tabs(c).length).toBeGreaterThan(4)
    expect(tabLabels(c)).toContain('Overview')
    expect(tabLabels(c)).toContain('Assess')
  })

  it('leaves the workflow numbered 1..n as before', async () => {
    ACCESS = null
    const c = await signIn()
    const nums = tabs(c).map((t) => t.querySelector('.stepnum')?.textContent).filter(Boolean)
    expect(nums).toEqual(['1', '2', '3', '4', '5'])
  })
})

describe('an unenforced payload changes nothing either', () => {
  it('ignores the calculated role while the flag is off', async () => {
    // The §15 Observe step writes roles and reports what they WOULD give, with `enforced: false`.
    // Applying that preview to the navigation would make step 1 of the rollout — the step whose
    // entire purpose is changing nothing anyone can see — visibly narrow the product.
    ACCESS = {
      enforced: false, role: { id: 'viewer', name: 'Viewer' },
      tabs: allTabs('operate'), capabilities: [],
      calculated: { tabs: { ...allTabs('hidden'), overview: 'view' }, capabilities: [] },
    }
    const c = await signIn()
    expect(tabLabels(c)).toContain('Remediate')
    expect(tabLabels(c)).toContain('Release')
  })
})

// ── enforcement (PRD §10) ─────────────────────────────────────────────────────

describe('an enforced role decides which tabs exist', () => {
  const reviewer = {
    enforced: true, role: { id: 'remediation-reviewer', name: 'Remediation Reviewer' },
    tabs: { overview: 'view', integrations: 'view', discover: 'view', assess: 'view',
            remediate: 'operate', publish: 'view', monitor: 'view',
            liveops: 'hidden', analytics: 'view', settings: 'hidden' },
    capabilities: ['remediate.view', 'remediate.run', 'remediate.review'],
  }

  // THE CONTROL for the test below, and it is not optional. The demo persona's own `me.allow`
  // (sim.js) already excludes liveops, analytics and acr, so `not.toContain('Live Operations')`
  // passes whether or not this feature works — the first draft of this file asserted exactly
  // that and proved nothing. Release is a tab the persona HAS, and this test is what establishes
  // it is there to be hidden.
  //
  // Two tests rather than one: mounting App twice inside a single test leaves module state
  // behind (the second mount never shows the sign-in screen), which failed six tests in a way
  // that looked like a bug in the feature.
  it('shows Release for a role that has it — the control', async () => {
    ACCESS = reviewer
    expect(tabLabels(await signIn())).toContain('Release')
  })

  it('removes a hidden tab from the navigation entirely', async () => {
    ACCESS = { ...reviewer, tabs: { ...reviewer.tabs, publish: 'hidden' } }
    const c = await signIn()
    expect(tabLabels(c)).not.toContain('Release')
    expect(tabLabels(c)).toContain('Remediate')
  })

  it('keeps a view-only tab present — visible is not the same as operable', async () => {
    // The distinction PRD §5 exists for. A Reviewer can SEE Assess; collapsing view into hidden
    // would take away the context they review against.
    ACCESS = reviewer
    const c = await signIn()
    expect(tabLabels(c)).toContain('Assess')
  })

  it('renumbers the workflow over the tabs that are actually there', async () => {
    // Discover hidden: the stepper must read 1,2,3,4 and not 2,3,4,5 — the second tells the user
    // they have skipped something rather than that it was never theirs to do.
    ACCESS = { ...reviewer, tabs: { ...reviewer.tabs, discover: 'hidden' } }
    const c = await signIn()
    expect(tabLabels(c)).not.toContain('Discover')
    const nums = tabs(c).map((t) => t.querySelector('.stepnum')?.textContent).filter(Boolean)
    expect(nums).toEqual(['1', '2', '3', '4'])
    expect(tabNamed(c, 'Assess').querySelector('.stepnum').textContent).toBe('1')
  })

  it('leaves the ungoverned tabs alone', async () => {
    // Conformance is authorized per-report by acr_authz (PRD §3 says not to touch it) and is not
    // in §6's governed list. A workspace role that hid it would be this feature quietly taking
    // over a boundary it was told to leave.
    // Knowledge Graph rather than Conformance for the same reason as above: this persona's
    // `me.allow` does not include acr, so asserting on it would prove nothing. Both are in
    // UNGOVERNED_TABS, and `graph` is the one this session can actually see.
    ACCESS = { ...reviewer, tabs: allTabs('hidden') }
    const c = await signIn()
    expect(tabLabels(c)).toContain('Knowledge Graph')
  })
})

// ── §9: a role change reaches a live session ──────────────────────────────────

describe('a role changed by an administrator reaches an open session', () => {
  it('re-reads access when the user comes back to the tab', async () => {
    // §9: "Users whose permissions change during an active session receive the new permissions on
    // their next API request. Navigation refreshes automatically." Without this the user works on
    // a stale navigation until they sign out — clicking tabs the server has started refusing.
    ACCESS = { enforced: true, role: { id: 'compliance-manager', name: 'Compliance Manager' },
               tabs: allTabs('operate'), capabilities: [] }
    const c = await signIn()
    expect(tabLabels(c)).toContain('Release')

    ACCESS = { ...ACCESS, tabs: { ...allTabs('operate'), publish: 'hidden' } }
    await act(async () => { window.dispatchEvent(new Event('focus')) })
    await flush()
    expect(getMyAccess).toHaveBeenCalled()
    expect(tabLabels(c)).not.toContain('Release')
  })

  it('keeps the session working when the refresh fails', async () => {
    // A network blip is not a permission decision. Narrowing the navigation on a failed refresh
    // would make a flaky connection look like a revoked role — and the user cannot tell which.
    ACCESS = { enforced: true, role: { id: 'compliance-manager', name: 'Compliance Manager' },
               tabs: allTabs('operate'), capabilities: [] }
    const c = await signIn()
    getMyAccess.mockResolvedValueOnce(null)
    await act(async () => { window.dispatchEvent(new Event('focus')) })
    await flush()
    expect(tabLabels(c)).toContain('Release')
  })
})

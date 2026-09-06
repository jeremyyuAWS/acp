/**
 * An open role dropdown must survive App's background polling.
 *
 * REPORTED: "the dropdown to assign a role keeps closing before I can assign."
 *
 * THE MECHANISM, AND WHY IT IS ASSERTED AS A DOM WRITE COUNT RATHER THAN AS "THE POPUP IS OPEN".
 * A native <select> popup is browser chrome, not DOM — jsdom has no popup, headless Chromium does
 * not paint one, and no browser fires an event when one is dismissed. So the popup's own state is
 * not observable at any level this suite can reach. What IS observable, and what actually closes
 * it, is the write: re-asserting the selection of a select whose popup is open tears the popup
 * down.
 *
 * React makes that write on EVERY commit of a <select>, not only when its value changed —
 * `diffProperties` returns a non-null update payload for the 'select' case unconditionally, so
 * `commitUpdate` runs and `postUpdateWrapper` → `updateOptions` sets `option.selected` again.
 * Measured on the unfixed component, with one unrelated ancestor re-render and nothing else:
 *
 *     2 selects → { optionSelected: 2 }, and three more re-renders → { optionSelected: 6 }
 *
 * App drives those re-renders on four unconditional timers while People is on screen:
 * `setActiveWorkflows(r?.active_workflows || [])` every 15 s (a fresh [] literal, so the reference
 * changes even when idle), `setBackendLastChecked(Date.now())` every 30 s, `setTick` and
 * `setScanList` every 60 s. Several times a minute, forever — and reading down a list of role
 * names takes longer than fifteen seconds.
 *
 * The fix memoises PersonRow so the poll never reaches the select. This file guards the property
 * that fix depends on, which is not "PersonRow is wrapped in memo" but "no write reaches the
 * select". Those differ: a callback prop rebuilt each render defeats the memo while leaving it
 * visibly in place, and the screen looks identical either way.
 *
 * `selected` is deliberately not reflected to an attribute by the HTML spec, so a MutationObserver
 * cannot see this. Instrumenting the property setter is the only way to count it.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement, useState, useEffect } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const ROLES = {
  roles: [
    { id: 'compliance-manager', name: 'Compliance Manager' },
    { id: 'analyst', name: 'Analyst' },
  ],
  enforced: true,
}

let ROSTER
const getPeople = vi.fn(async () => ({ people: ROSTER, domains: [], invite_enabled: false, can_manage: true }))
const assignWorkspaceRole = vi.fn(async (email, roleId) => {
  ROSTER = ROSTER.map((p) => (p.email === email ? { ...p, workspace_role_id: roleId || null } : p))
  return { person: {} }
})

vi.mock('./api.js', async (importActual) => ({
  ...(await importActual()),
  getPeople,
  getWorkspaceRoles: vi.fn(async () => ROLES),
  assignWorkspaceRole,
  roleImpact: vi.fn(async () => ({ gains: [], loses: [], enforced: true })),
  addPerson: vi.fn(), removePerson: vi.fn(), updatePerson: vi.fn(),
}))

const { default: PeopleAccess } = await import('./PeopleAccess.jsx')

// Count React's writes to the selection of any <option>/<select> on the page.
const writes = { optionSelected: 0, selectValue: 0 }
let restore = []
function instrumentSelectionWrites() {
  const optDesc = Object.getOwnPropertyDescriptor(window.HTMLOptionElement.prototype, 'selected')
  Object.defineProperty(window.HTMLOptionElement.prototype, 'selected', {
    ...optDesc,
    set(v) { writes.optionSelected += 1; optDesc.set.call(this, v) },
  })
  const selDesc = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value')
  Object.defineProperty(window.HTMLSelectElement.prototype, 'value', {
    ...selDesc,
    set(v) { writes.selectValue += 1; selDesc.set.call(this, v) },
  })
  restore = [
    () => Object.defineProperty(window.HTMLOptionElement.prototype, 'selected', optDesc),
    () => Object.defineProperty(window.HTMLSelectElement.prototype, 'value', selDesc),
  ]
}

// Stands in for App: owns state, polls it on a timer, renders People as a descendant. This is the
// whole shape of the bug — nothing here touches People, and that is the point.
let pollApp
function AppLikeAncestor() {
  const [activeWorkflows, setActiveWorkflows] = useState([])
  useEffect(() => { pollApp = () => setActiveWorkflows([]) }, [])
  return createElement('div', { 'data-workflows': activeWorkflows.length },
    createElement(PeopleAccess))
}

const mount = async () => {
  const { root } = createTestRoot()
  await act(async () => { root.render(createElement(AppLikeAncestor)) })
  await act(async () => {})
}

beforeEach(() => {
  ROSTER = [
    { email: 'ana@x.com', status: 'active', role: 'user', provider: 'google', workspace_role_id: 'analyst' },
    { email: 'bo@x.com', status: 'active', role: 'user', provider: 'google', workspace_role_id: null },
  ]
  writes.optionSelected = 0
  writes.selectValue = 0
  instrumentSelectionWrites()
})
afterEach(async () => {
  await unmountAll()
  restore.forEach((f) => f())
  restore = []
})

describe('the People selects are not re-committed by an unrelated re-render', () => {
  it('writes nothing to any select when an ancestor polls', async () => {
    await mount()
    expect(document.querySelectorAll('select.people-select').length).toBeGreaterThan(0)

    writes.optionSelected = 0
    writes.selectValue = 0
    // One App poll. `setActiveWorkflows([])` with a fresh literal — the real one, verbatim.
    await act(async () => { pollApp() })

    expect(writes).toEqual({ optionSelected: 0, selectValue: 0 })
  })

  it('still writes nothing after four polls, which is one minute of real time', async () => {
    await mount()
    writes.optionSelected = 0
    writes.selectValue = 0

    for (let i = 0; i < 4; i += 1) await act(async () => { pollApp() })

    // Without the memo this was 2 per poll per select. The count is asserted rather than
    // "is it zero-ish": a fix that merely reduced the rate would still shut the popup, just less
    // often, and would read as fixed to anyone clicking quickly.
    expect(writes).toEqual({ optionSelected: 0, selectValue: 0 })
  })

  it('does not freeze the row: a real assignment still repaints it', async () => {
    await mount()
    const select = [...document.querySelectorAll('select.people-select')]
      .find((s) => s.getAttribute('aria-label') === 'Workspace role for bo@x.com')
    expect(select.value).toBe('')

    // The memo must bail out on a poll and NOT on real data. A row that stopped updating would
    // be the same reported symptom by the opposite cause, and equally invisible in a screenshot.
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set
      setter.call(select, 'analyst')
      select.dispatchEvent(new window.Event('change', { bubbles: true }))
    })
    await act(async () => {})

    const after = [...document.querySelectorAll('select.people-select')]
      .find((s) => s.getAttribute('aria-label') === 'Workspace role for bo@x.com')
    expect(after.value).toBe('analyst')
    expect(assignWorkspaceRole).toHaveBeenCalledWith('bo@x.com', 'analyst')
  })
})

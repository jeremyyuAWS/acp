/**
 * The People row's TWO selects — telling them apart, and both of them actually responding.
 *
 * REPORTED: "it looks to be two drop downs and neither of them really work."
 *
 * Both halves of that were true, and they are different bugs.
 *
 * LOOKS LIKE TWO DROP DOWNS. It is two, and they control different things: the ACCESS LEVEL
 * (User / Platform Admin — may they touch platform settings) and the WORKSPACE ROLE (which tabs
 * they see). Nothing on screen said so. The row is a five-column grid with no header, the only
 * labels were `aria-label`s, and styles.css had deliberately unified their appearance so they
 * would stop looking like "two different widgets" — which succeeded, and left two identical
 * controls side by side with nothing to distinguish them. A workspace role NAMED "Platform Admin"
 * then made both read the same words, which is what the screenshot showed.
 *
 * NEITHER WORKS. The workspace-role select paints optimistically (`showRole`) because that exact
 * bug — "the dropdown does not do anything" — was reported and fixed for it. `change()`, the
 * access-level path, never got the same treatment: it is controlled by `person.role` and updates
 * state only when the response lands, so for the length of the round trip the select springs back
 * to the old value under the user's cursor. On a slow request it reads as a dead control, which
 * is precisely the complaint.
 *
 * The deferred promise below is the point of this file: asserting after `await` would pass
 * against the broken version too, because the value is correct once the response arrives. The bug
 * only exists in the window between.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const ROLES = {
  roles: [
    // Named to match the screenshot: a WORKSPACE role called "Platform Admin", which is also an
    // ACCESS LEVEL name. Both selects then read "Platform Admin" and nothing says which is which.
    { id: 'platform-admin', name: 'Platform Admin', users: 1 },
    { id: 'analyst', name: 'Analyst', users: 0 },
  ],
  enforced: true,
}

let ROSTER
let deferred          // resolve updatePerson by hand, to observe the in-flight window

const getPeople = vi.fn(async () => ({ people: ROSTER, domains: [], invite_enabled: false, can_manage: true }))
const updatePerson = vi.fn((email, patch) => new Promise((resolve) => {
  deferred = () => {
    ROSTER = ROSTER.map((p) => (p.email === email ? { ...p, ...patch } : p))
    resolve({ person: ROSTER.find((p) => p.email === email), people: ROSTER })
  }
}))

vi.mock('./api.js', async (importActual) => ({
  ...(await importActual()),
  getPeople,
  getWorkspaceRoles: vi.fn(async () => ROLES),
  updatePerson,
  addPerson: vi.fn(), removePerson: vi.fn(),
  assignWorkspaceRole: vi.fn(async () => ({ person: {} })),
  roleImpact: vi.fn(async () => ({ gains: [], loses: [], enforced: true })),
}))

const { default: PeopleAccess } = await import('./PeopleAccess.jsx')

afterEach(() => { unmountAll(); vi.clearAllMocks() })
beforeEach(() => {
  deferred = null
  ROSTER = [
    { email: 'jane@hosp.org', provider: 'microsoft', role: 'user', status: 'access_ready',
      workspace_role_id: 'platform-admin' },
  ]
})

let container
const mount = async () => {
  const created = createTestRoot()
  container = created.container
  await act(async () => { created.root.render(createElement(PeopleAccess)) })
  await act(async () => { await Promise.resolve() })
  return container
}

const accessSelect = () => container.querySelector('select[aria-label^="Access level"]')
const roleSelect = () => container.querySelector('select[aria-label^="Workspace role"]')

const choose = async (el, value) => {
  const setter = Object.getOwnPropertyDescriptor(
    el.ownerDocument.defaultView.HTMLSelectElement.prototype, 'value').set
  await act(async () => {
    setter.call(el, value)
    el.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

describe('the access-level select responds immediately', () => {
  it('shows the chosen level WHILE the request is still in flight', async () => {
    await mount()
    expect(accessSelect().value).toBe('user')

    await choose(accessSelect(), 'admin')

    // The request has not been answered yet — `deferred` is still pending. This is the whole
    // window the bug lived in: the select was re-rendered from `person.role`, which is still
    // "user", so it snapped back under the cursor and read as a dead control.
    expect(updatePerson).toHaveBeenCalledWith('jane@hosp.org', { role: 'admin' })
    expect(accessSelect().value).toBe('admin')

    await act(async () => { deferred(); await Promise.resolve() })
    expect(accessSelect().value).toBe('admin')
  })

  it('falls back to the truth when the server refuses', async () => {
    // The optimistic paint is a guess. When it is wrong the row must show what the server kept,
    // not what the user clicked — an optimistic update that survives a failure is a lie that
    // looks like a success.
    await mount()
    updatePerson.mockImplementationOnce(() => Promise.reject(new Error('not allowed')))
    await choose(accessSelect(), 'admin')
    await act(async () => { await Promise.resolve() })
    await act(async () => { await Promise.resolve() })
    expect(accessSelect().value).toBe('user')
    expect(container.textContent).toMatch(/not allowed/)
  })
})

describe('the two selects are distinguishable', () => {
  it('gives every row select a VISIBLE column heading, not just an aria-label', async () => {
    // The reported symptom: two identical controls, nothing on screen saying which is which.
    // A screen-reader user had `aria-label`s; a sighted user had nothing (3.3.2).
    await mount()
    const header = container.querySelector('.people-head')
    expect(header, 'the roster has no column header row').toBeTruthy()
    expect(header.textContent).toMatch(/Access level/i)
    expect(header.textContent).toMatch(/Workspace role/i)
  })

  it('still tells them apart when a workspace role is also named "Platform Admin"', async () => {
    // Exactly the screenshot: both selects display the same words. The headings are the only
    // thing that disambiguates them, which is why they are asserted rather than assumed.
    await mount()
    expect(accessSelect().value).toBe('user')
    expect(roleSelect().selectedOptions[0].textContent).toBe('Platform Admin')
    const header = container.querySelector('.people-head')
    const headings = [...header.children].map((c) => c.textContent.trim()).filter(Boolean)
    expect(headings).toContain('Access level')
    expect(headings).toContain('Workspace role')
  })

  it('keeps the header aligned to the same grid as the rows', async () => {
    // A header on a different grid is worse than none: it labels the wrong column. Both must
    // carry has-role-column so the tracks line up.
    await mount()
    const header = container.querySelector('.people-head')
    const row = container.querySelector('.people-row')
    expect(row.classList.contains('has-role-column')).toBe(true)
    expect(header.classList.contains('has-role-column')).toBe(true)
  })
})

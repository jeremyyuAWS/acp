/**
 * Assigning a workspace role from the People screen, and the confirmation that precedes it (§9).
 *
 * THE CONFIRMATION IS THE POINT, and specifically the half nobody can work out for themselves.
 * "Change Jane from Compliance Manager to Analyst?" is a question an administrator cannot answer
 * from the two names — what they need to know is which of Jane's current abilities disappear, and
 * that requires resolving both roles. So the preview is computed SERVER-SIDE by the same resolver
 * the gate uses, and this file checks the screen shows it rather than inventing its own diff.
 *
 * A preview that disagrees with what actually happens is worse than no preview at all: it is read,
 * approved, and then something else occurs.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const PEOPLE = {
  people: [
    { email: 'owner@hosp.org', provider: 'google', role: 'admin', status: 'access_ready', protected: true },
    { email: 'jane@hosp.org', provider: 'microsoft', role: 'user', status: 'access_ready',
      workspace_role_id: 'compliance-manager' },
  ],
  domains: [], invite_enabled: false, can_manage: true,
}
const ROLES = {
  roles: [
    { id: 'compliance-manager', name: 'Compliance Manager', users: 1 },
    { id: 'analyst', name: 'Analyst', users: 0 },
  ],
  enforced: true,
}

let IMPACT = { gains: ['discover.run'], loses: ['remediate.run', 'release.view'], enforced: true }
const assignWorkspaceRole = vi.fn(async () => ({ person: {} }))
const roleImpact = vi.fn(async () => IMPACT)
const getPeople = vi.fn(async () => PEOPLE)

vi.mock('./api.js', async (importActual) => ({
  ...(await importActual()),
  getPeople,
  getWorkspaceRoles: vi.fn(async () => ROLES),
  assignWorkspaceRole,
  roleImpact,
  addPerson: vi.fn(), removePerson: vi.fn(), updatePerson: vi.fn(),
}))

const { default: PeopleAccess } = await import('./PeopleAccess.jsx')

afterEach(() => { unmountAll(); vi.clearAllMocks() })
beforeEach(() => {
  IMPACT = { gains: ['discover.run'], loses: ['remediate.run', 'release.view'], enforced: true }
  // The mock returns ROLES by reference, so a test that changes the rung has to put it back or
  // the next one inherits it — the same trap the JIT-roster memo sprang on test_staged_rollout.
  ROLES.enforced = true
  delete ROLES.rollout
})

const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve() }) }
const click = async (el) => { await act(async () => { el.click() }); await flush() }
const byText = (c, sel, re) => [...c.querySelectorAll(sel)].find((e) => re.test(e.textContent))

async function mount() {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(PeopleAccess)) })
  await flush()
  return container
}

const roleSelect = (c) => c.querySelector('select[aria-label="Workspace role for jane@hosp.org"]')

async function pick(c, value) {
  const sel = roleSelect(c)
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set.call(sel, value)
    sel.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await flush()
}

// ── the control ───────────────────────────────────────────────────────────────

describe('the role column', () => {
  it('offers every role, plus explicitly no role', async () => {
    const c = await mount()
    expect([...roleSelect(c).options].map((o) => o.textContent))
      .toEqual(['No role', 'Compliance Manager', 'Analyst'])
  })

  it('shows the role the person currently holds', async () => {
    const c = await mount()
    expect(roleSelect(c).value).toBe('compliance-manager')
  })

  it('does not offer to change the protected owner', async () => {
    const c = await mount()
    expect(c.querySelector('select[aria-label="Workspace role for owner@hosp.org"]')).toBeNull()
    expect(c.textContent).toContain('Owner — full access')
  })
})

// ── the confirmation (PRD §9) ─────────────────────────────────────────────────

describe('changing a role asks first', () => {
  it('does not assign anything until the change is confirmed', async () => {
    const c = await mount()
    await pick(c, 'analyst')
    expect(assignWorkspaceRole).not.toHaveBeenCalled()
    expect(c.querySelector('[role="dialog"]')).toBeTruthy()
  })

  it('names what is LOST as well as what is gained', async () => {
    // The lost half is the one an administrator cannot derive from two role names, and the one
    // that generates the support ticket when it is a surprise.
    const c = await mount()
    await pick(c, 'analyst')
    const dialog = c.querySelector('[role="dialog"]')
    expect(dialog.textContent).toContain('remediate.run')
    expect(dialog.textContent).toContain('release.view')
    expect(dialog.textContent).toContain('discover.run')
    expect(dialog.textContent).toContain('Analyst')
  })

  it('asks the server for the impact rather than diffing two role names in the browser', async () => {
    const c = await mount()
    await pick(c, 'analyst')
    expect(roleImpact).toHaveBeenCalledWith('jane@hosp.org', 'analyst')
  })

  it('assigns once confirmed', async () => {
    const c = await mount()
    await pick(c, 'analyst')
    await click(byText(c, '[role="dialog"] button', /^Change role$/))
    expect(assignWorkspaceRole).toHaveBeenCalledWith('jane@hosp.org', 'analyst')
  })

  it('assigns nothing when cancelled', async () => {
    const c = await mount()
    await pick(c, 'analyst')
    await click(byText(c, '[role="dialog"] button', /^Cancel$/))
    expect(assignWorkspaceRole).not.toHaveBeenCalled()
    expect(c.querySelector('[role="dialog"]')).toBeNull()
  })

  it('says plainly when nothing actually changes', async () => {
    // Two roles can differ in name and not in effect. Showing two empty lists would read as a
    // broken preview; saying so is the honest version.
    IMPACT = { gains: [], loses: [], enforced: true }
    const c = await mount()
    await pick(c, 'analyst')
    expect(c.querySelector('[role="dialog"]').textContent).toMatch(/Nothing they can do today changes/i)
  })

  it('warns that the change is inert while enforcement is off', async () => {
    IMPACT = { gains: [], loses: [], enforced: false, mode: 'observe' }
    const c = await mount()
    await pick(c, 'analyst')
    expect(c.querySelector('[role="dialog"]').textContent).toContain('changes nothing for them')
  })

  it('does NOT call the change inert at the navigation stage, because it is not', async () => {
    // The tabs disappear for them on their next load while the server still answers a direct
    // request. Reusing the "changes nothing" copy here would tell an administrator they had not
    // altered somebody's access at the exact moment they did.
    IMPACT = { gains: [], loses: ['operations.view'], enforced: false, mode: 'navigation' }
    const c = await mount()
    await pick(c, 'analyst')
    const text = c.querySelector('[role="dialog"]').textContent
    expect(text).toContain('hide tabs for them')
    expect(text).not.toContain('changes nothing for them')
  })
})

describe('when the preview cannot be fetched', () => {
  it('still lets the change proceed, and says the preview is missing', async () => {
    // The confirmation is a courtesy; the assignment is the operation. Blocking a legitimate
    // change because a read failed would make a broken preview into an outage.
    roleImpact.mockRejectedValueOnce(new Error('nope'))
    const c = await mount()
    await pick(c, 'analyst')
    const dialog = c.querySelector('[role="dialog"]')
    expect(dialog.textContent).toMatch(/could not be previewed/i)
    await click(byText(c, '[role="dialog"] button', /^Change role$/))
    expect(assignWorkspaceRole).toHaveBeenCalledWith('jane@hosp.org', 'analyst')
  })
})

describe('when the caller may not manage roles', () => {
  it('hides the role column rather than showing an empty one', async () => {
    // GET /admin/roles 403s for them. An empty select reads as a broken control; absent reads as
    // "not yours", which is what it is.
    const api = await import('./api.js')
    api.getWorkspaceRoles.mockRejectedValueOnce(new Error('403'))
    const c = await mount()
    expect(roleSelect(c)).toBeNull()
    expect(c.querySelector('[role="status"]').textContent).toBe('')
  })
})


// ── the rung, on the screen where roles are actually given ───────────────────

describe('an assignment that will not do anything yet says so', () => {
  // WorkspaceRoles.jsx has carried this warning since slice 6, on the screen where roles are
  // DESIGNED. The screen where they are ASSIGNED said nothing: the dropdown changed, "Jane's role
  // was updated" appeared in green, and every route still admitted her exactly as before. An
  // administrator doing the thing the rollout runbook asks for, at the step the runbook names,
  // got no signal that the step has not taken effect yet.
  //
  // The server has always sent the rung on this very request — `enforced` and `rollout` ride back
  // from GET /admin/workspace-roles beside the roles the dropdown is built from — so the
  // information was in the response this component was discarding.

  const note = (c) => byText(c, '[role="note"]', /not being enforced/i)

  it('names the rung and what it means, in the server\'s words', async () => {
    ROLES.enforced = false
    ROLES.rollout = { mode: 'observe', means: 'Roles are calculated and recorded; nobody is refused.',
                      next: 'navigation' }
    const c = await mount()
    expect(note(c)).toBeTruthy()
    expect(note(c).textContent).toContain('calculated and recorded')
    expect(note(c).textContent).toContain('navigation')
  })

  it('still warns when the server sends no rung detail', async () => {
    // An older server, or a payload without `rollout`. The fallback wording has to stand alone —
    // a note that renders empty is worse than no note, because it reads as a rendering bug.
    ROLES.enforced = false
    const c = await mount()
    expect(note(c).textContent).toMatch(/nothing changes for anyone/i)
  })

  it('says nothing when roles ARE enforced — the control', async () => {
    // Without this, "the note appears" is satisfiable by a note that always appears, which would
    // train an administrator to ignore the one screen that has to be believed.
    const c = await mount()          // ROLES.enforced === true, from beforeEach
    expect(note(c)).toBeFalsy()
  })

  it('says nothing when there are no roles to assign', async () => {
    // No dropdown means no action to qualify, and a warning about the effect of something nobody
    // can do is noise. Restored explicitly because this test mutates the shared fixture.
    const previous = ROLES.roles
    ROLES.roles = []
    ROLES.enforced = false
    try {
      const c = await mount()
      expect(note(c)).toBeFalsy()
    } finally {
      ROLES.roles = previous
    }
  })
})

/**
 * Assigning a workspace role from the People screen, and the toast that reports it (§9).
 *
 * IT USED TO ASK FIRST. A modal confirmation opened on every change, named the server-computed
 * impact, and saved only when accepted. That was removed on request: assigning roles across a
 * roster is repetitive, and a dialog per row makes it a two-step act every time.
 *
 * WHAT THE DIALOG CARRIED HAD TO SURVIVE THE REMOVAL, and that is most of what this file is
 * about. "Change Jane from Compliance Manager to Analyst?" is a question an administrator cannot
 * answer from the two names — the consequential half is which of Jane's current abilities
 * disappear, and that requires resolving both roles. So the preview is still computed SERVER-SIDE
 * by the same resolver the gate uses; it now appears in the toast, after the fact, in the past
 * tense, beside an Undo.
 *
 * A preview that disagrees with what actually happened is worse than no preview at all: it is
 * read, believed, and something else is true.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const ROLES = {
  roles: [
    { id: 'compliance-manager', name: 'Compliance Manager', users: 1 },
    { id: 'analyst', name: 'Analyst', users: 0 },
  ],
  enforced: true,
}

// A ROSTER THAT ACTUALLY CHANGES, rather than a frozen fixture.
//
// The component re-reads people after every assignment, so a getPeople that always answers with
// the ORIGINAL role would paint the change and then immediately revert it — the optimistic update
// and the Undo would both look broken here while working in the product, and, worse, a genuinely
// broken Undo would look fine. The mock below is a small fake server: assignWorkspaceRole writes,
// getPeople reads back what was written.
let ROSTER
let IMPACT
// Which endpoint was called in which order. The order is load-bearing — see the test that reads it.
let CALLS

const getPeople = vi.fn(async () => ({ people: ROSTER, domains: [], invite_enabled: false, can_manage: true }))
const assignWorkspaceRole = vi.fn(async (email, roleId) => {
  CALLS.push(`assign:${roleId}`)
  ROSTER = ROSTER.map((p) => (p.email === email ? { ...p, workspace_role_id: roleId || null } : p))
  return { person: {} }
})
const roleImpact = vi.fn(async () => { CALLS.push('impact'); return IMPACT })

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
  ROSTER = [
    { email: 'owner@hosp.org', provider: 'google', role: 'admin', status: 'access_ready', protected: true },
    { email: 'jane@hosp.org', provider: 'microsoft', role: 'user', status: 'access_ready',
      workspace_role_id: 'compliance-manager' },
  ]
  IMPACT = { gains: ['discover.run'], loses: ['remediate.run', 'release.view'], enforced: true }
  CALLS = []
  // The mock returns ROLES by reference, so a test that changes the rung has to put it back or
  // the next one inherits it — the same trap the JIT-roster memo sprang on test_staged_rollout.
  ROLES.enforced = true
  delete ROLES.rollout
})

const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve() }) }
const click = async (el) => { await act(async () => { el.click() }); await flush() }
const byText = (c, sel, re) => [...c.querySelectorAll(sel)].find((e) => re.test(e.textContent))

// THE TOAST IS NOT INSIDE THE COMPONENT, and that is deliberate rather than incidental. It is
// `position: fixed`, and Settings' `.setoverlay` carries a `backdrop-filter`, which would make it
// the containing block and pin the toast to the corner of a scrolling panel instead of the
// window — the exact defect that made the old confirmation invisible. It is portalled to
// document.body, so these lookups go through `document`. See peopleDialogPortal.test.jsx.
const toast = () => document.querySelector('.people-toast')

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

// ── it applies at once, and says so ──────────────────────────────────────────

describe('changing a role applies immediately', () => {
  it('assigns on selection, with nothing to confirm first', async () => {
    const c = await mount()
    await pick(c, 'analyst')
    expect(assignWorkspaceRole).toHaveBeenCalledWith('jane@hosp.org', 'analyst')
    // The whole of the old flow, asserted absent: no dialog, no scrim, nothing to accept.
    expect(document.querySelector('[role="dialog"]')).toBeNull()
  })

  it('leaves the new role showing on the row rather than snapping back', async () => {
    const c = await mount()
    await pick(c, 'analyst')
    expect(roleSelect(c).value).toBe('analyst')
  })

  it('shows the new role BEFORE the server answers', async () => {
    // The select is controlled by the person's stored role, so without an optimistic paint it
    // reverts for the length of the round trip. On the screen whose reported bug was "the
    // dropdown does not do anything", a control that visibly undoes the user is the one
    // behaviour that must not ship. Held open deliberately: this asserts the state DURING the
    // request, which is the only moment the defect would be visible.
    let release
    assignWorkspaceRole.mockImplementationOnce(() => new Promise((r) => { release = r }))
    const c = await mount()
    await pick(c, 'analyst')
    expect(roleSelect(c).value).toBe('analyst')
    await act(async () => { release({ person: {} }) })
  })

  it('does nothing at all when the selected role is the one already held', async () => {
    const c = await mount()
    await pick(c, 'compliance-manager')
    expect(assignWorkspaceRole).not.toHaveBeenCalled()
    expect(toast()).toBeNull()
  })
})

describe('the toast reports what changed', () => {
  it('names what was LOST as well as what was gained', async () => {
    // The lost half is the one an administrator cannot derive from two role names, and the one
    // that generates the support ticket when it is a surprise.
    const c = await mount()
    await pick(c, 'analyst')
    expect(toast().textContent).toContain('remediate.run')
    expect(toast().textContent).toContain('release.view')
    expect(toast().textContent).toContain('discover.run')
    expect(toast().textContent).toContain('Analyst')
  })

  it('speaks in the past tense, because the change has already happened', async () => {
    // The dialog said "they will lose". Copy that still reads as a forecast invites the reader to
    // look for something left to approve, and there no longer is one.
    const c = await mount()
    await pick(c, 'analyst')
    const text = toast().textContent
    expect(text).toContain('Lost:')
    expect(text).not.toMatch(/will lose/i)
  })

  it('asks the server for the impact rather than diffing two role names in the browser', async () => {
    const c = await mount()
    await pick(c, 'analyst')
    expect(roleImpact).toHaveBeenCalledWith('jane@hosp.org', 'analyst')
  })

  it('asks for the impact BEFORE the assignment lands, not after', async () => {
    // The order is the whole correctness of the preview. The impact is the difference between the
    // role held NOW and the one being moved to; asked after the write, the server compares the
    // new role with itself and answers "nothing changes" every time. That failure is invisible —
    // an always-empty preview reads as a fact about the two roles rather than about when it was
    // requested — so it is pinned here rather than left to review.
    const c = await mount()
    await pick(c, 'analyst')
    expect(CALLS).toEqual(['impact', 'assign:analyst'])
  })

  it('says plainly when nothing actually changes', async () => {
    // Two roles can differ in name and not in effect. Showing two empty lists would read as a
    // broken preview; saying so is the honest version.
    IMPACT = { gains: [], loses: [], enforced: true }
    const c = await mount()
    await pick(c, 'analyst')
    expect(toast().textContent).toMatch(/Nothing they can do today changes/i)
  })

  it('warns that the change is inert while enforcement is off', async () => {
    IMPACT = { gains: [], loses: [], enforced: false, mode: 'observe' }
    const c = await mount()
    await pick(c, 'analyst')
    expect(toast().textContent).toContain('changes nothing for them')
  })

  it('does NOT call the change inert at the navigation stage, because it is not', async () => {
    // The tabs disappear for them on their next load while the server still answers a direct
    // request. Reusing the "changes nothing" copy here would tell an administrator they had not
    // altered somebody's access at the exact moment they did.
    IMPACT = { gains: [], loses: ['operations.view'], enforced: false, mode: 'navigation' }
    const c = await mount()
    await pick(c, 'analyst')
    const text = toast().textContent
    expect(text).toContain('hides tabs for them')
    expect(text).not.toContain('changes nothing for them')
  })

  it('can be dismissed', async () => {
    const c = await mount()
    await pick(c, 'analyst')
    await click(byText(document, '.people-toast button', /^×$/))
    expect(toast()).toBeNull()
  })
})

// ── undo, which is what Cancel became ────────────────────────────────────────

describe('the toast can undo the change it reports', () => {
  it('puts the previous role back, on the server', async () => {
    // Without this the screen assigns on one stray change event with no way back except knowing
    // what the previous role was — which, for a role the administrator did not set themselves,
    // they do not.
    const c = await mount()
    await pick(c, 'analyst')
    await click(byText(document, '.people-toast button', /^Undo$/))
    expect(assignWorkspaceRole).toHaveBeenLastCalledWith('jane@hosp.org', 'compliance-manager')
    expect(ROSTER.find((p) => p.email === 'jane@hosp.org').workspace_role_id).toBe('compliance-manager')
  })

  it('puts the previous role back on the row too', async () => {
    const c = await mount()
    await pick(c, 'analyst')
    await click(byText(document, '.people-toast button', /^Undo$/))
    expect(roleSelect(c).value).toBe('compliance-manager')
  })

  it('restores "no role" as a real previous value, not as an absent one', async () => {
    // '' is a legitimate role to return someone to, and the falsy-value bug here would be silent:
    // an Undo that quietly kept the new role while reporting success.
    ROSTER = ROSTER.map((p) => (p.email === 'jane@hosp.org' ? { ...p, workspace_role_id: null } : p))
    const c = await mount()
    await pick(c, 'analyst')
    await click(byText(document, '.people-toast button', /^Undo$/))
    expect(assignWorkspaceRole).toHaveBeenLastCalledWith('jane@hosp.org', '')
    expect(roleSelect(c).value).toBe('')
  })

  it('closes the toast, so one change cannot be undone twice', async () => {
    const c = await mount()
    await pick(c, 'analyst')
    await click(byText(document, '.people-toast button', /^Undo$/))
    expect(toast()).toBeNull()
  })
})

describe('when the preview cannot be fetched', () => {
  it('still makes the change, and says the preview is missing', async () => {
    // The preview is a courtesy; the assignment is the operation. Losing the write because a read
    // failed would make a broken preview into an outage — and now that nothing is confirmed
    // first, silently dropping the change would be invisible.
    roleImpact.mockRejectedValueOnce(new Error('nope'))
    const c = await mount()
    await pick(c, 'analyst')
    expect(assignWorkspaceRole).toHaveBeenCalledWith('jane@hosp.org', 'analyst')
    expect(toast().textContent).toMatch(/could not be previewed/i)
  })
})

describe('when the assignment itself fails', () => {
  it('reports the error and does not claim success', async () => {
    assignWorkspaceRole.mockRejectedValueOnce(new Error('403 Forbidden'))
    const c = await mount()
    await pick(c, 'analyst')
    expect(toast(), 'a failed assignment must not produce a "Role updated" toast').toBeNull()
    expect(c.querySelector('[role="status"]').textContent).toContain('403 Forbidden')
  })

  it('puts the row back to the role the server still holds', async () => {
    // The optimistic paint has to be undone by the truth rather than by guessing. getPeople is
    // the fake server above, and it never saw the write.
    assignWorkspaceRole.mockRejectedValueOnce(new Error('403 Forbidden'))
    const c = await mount()
    await pick(c, 'analyst')
    expect(roleSelect(c).value).toBe('compliance-manager')
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
  // from GET /admin/roles beside the roles the dropdown is built from — so the
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

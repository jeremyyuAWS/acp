/**
 * The role toast must not take clicks from the rows underneath it, and must retire when the
 * operator carries on working.
 *
 * REPORTED: the toast covers the dropdown.
 *
 * WHAT IS ACTUALLY WRONG, measured in Chromium against the real Settings chrome (.setoverlay →
 * .setpanel → .setbody), with the panel scrolled to the bottom, counting controls whose own
 * centre hit-tests to the toast rather than to themselves:
 *
 *     viewport      top:18 (was)   bottom:18   pointer-events:none
 *     1024x800        6 blocked     2 blocked       0 blocked
 *     1152x800        3 blocked     1 blocked       0 blocked
 *     1280x800        0 blocked     0 blocked       0 blocked
 *     1024x640        6 blocked     4 blocked       0 blocked
 *
 * Three things that table settles, none of which were obvious beforehand:
 *
 *   - IT ONLY HAPPENS SCROLLED, AND ONLY NARROW. Unscrolled, the Settings chrome pushes the first
 *     row below the toast's bottom edge (y=190) at every width — zero collisions. `.setbody`
 *     scrolls INTERNALLY with its top at ~y=126, above that edge, so rows ride up into the band.
 *     An earlier screenshot of this "bug" was taken on a bare page with no Settings chrome, which
 *     is a different layout and overstated it.
 *   - MOVING THE TOAST IS NOT A FIX. Bottom-right merely relocates the collision onto whichever
 *     rows are at the bottom, and in a short window it is WORSE than the corner it came from.
 *   - The overlap AREA is unchanged by the fix (9/6/0/9 either way). Only the interception goes.
 *     A fixed overlay on a scrolling list can always cover something; what it must never do is
 *     swallow the click.
 *
 * WHY THE CSS HALF IS ASSERTED AS SOURCE TEXT. jsdom has no layout engine and no real
 * `elementFromPoint`, so the hit-test above cannot run here at all — the browser measurement is
 * where that evidence comes from, and this is the regression guard for the declaration it rests
 * on. The precedent is cssCustomProperties.test.jsx, which reads the same file for the same
 * reason. The behavioural half below IS exercised properly.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const CSS = readFileSync(resolve(import.meta.dirname, 'styles.css'), 'utf8')

const ruleBody = (selector) => {
  const i = CSS.indexOf(selector + ' {')
  if (i === -1) return null
  return CSS.slice(i, CSS.indexOf('}', i))
}

describe('the toast lets the list underneath it be clicked', () => {
  it('.people-toast does not intercept pointer events', () => {
    const rule = ruleBody('.people-toast')
    expect(rule).not.toBeNull()
    expect(rule).toMatch(/pointer-events:\s*none/)
  })

  it('its own buttons take them back, or Undo and the dismiss × are dead', () => {
    // The failure this guards is silent in a screenshot: the toast renders perfectly and neither
    // button responds. Verified live in Chromium too — undo and dismiss both still act.
    const rule = ruleBody('.people-toast button')
    expect(rule).not.toBeNull()
    expect(rule).toMatch(/pointer-events:\s*auto/)
  })
})

// ── The behavioural half ──────────────────────────────────────────────────────────────────────
const ROLES = { roles: [{ id: 'analyst', name: 'Analyst' }], enforced: true }
let ROSTER
const getPeople = vi.fn(async () => ({ people: ROSTER, domains: [], invite_enabled: false, can_manage: true }))
const updatePerson = vi.fn(async (email, patch) => {
  ROSTER = ROSTER.map((p) => (p.email === email ? { ...p, ...patch } : p))
  return { person: ROSTER.find((p) => p.email === email) }
})
const removePerson = vi.fn(async () => ({}))
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
  updatePerson,
  removePerson,
  addPerson: vi.fn(),
}))

const { default: PeopleAccess } = await import('./PeopleAccess.jsx')

const setValue = (el, v) => {
  Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set.call(el, v)
  el.dispatchEvent(new window.Event('change', { bubbles: true }))
}
const sel = (label) => [...document.querySelectorAll('select.people-select')]
  .find((s) => s.getAttribute('aria-label') === label)

const mount = async () => {
  const { root } = createTestRoot()
  await act(async () => { root.render(createElement(PeopleAccess)) })
  await act(async () => {})
}
const raiseToast = async () => {
  await act(async () => { setValue(sel('Workspace role for bo@x.com'), 'analyst') })
  await act(async () => {})
  expect(document.querySelector('.people-toast')).not.toBeNull()
}

beforeEach(() => {
  ROSTER = [
    { email: 'ana@x.com', status: 'active', role: 'user', provider: 'google', workspace_role_id: 'analyst' },
    { email: 'bo@x.com', status: 'active', role: 'user', provider: 'google', workspace_role_id: null },
  ]
})
afterEach(async () => { await unmountAll(); vi.clearAllMocks() })

describe('the toast retires when the operator carries on', () => {
  it('replaces the previous role notice when platform administration changes', async () => {
    await mount()
    await raiseToast()

    await act(async () => { setValue(sel('Workspace role for ana@x.com'), '') })
    await act(async () => {})

    expect(document.querySelector('.people-toast').textContent).toContain('ana@x.com')
  })

  it('goes when someone is suspended', async () => {
    await mount()
    await raiseToast()

    const suspend = [...document.querySelectorAll('.people-row-actions button')]
      .find((b) => b.textContent === 'Suspend')
    await act(async () => { suspend.click() })
    await act(async () => {})

    expect(document.querySelector('.people-toast')).toBeNull()
  })

  it('goes when someone is removed — its Undo re-assigns a role BY EMAIL, possibly theirs', async () => {
    await mount()
    await raiseToast()
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    const removeBtn = [...document.querySelectorAll('.people-row-actions button')]
      .find((b) => b.textContent === 'Remove')
    await act(async () => { removeBtn.click() })
    await act(async () => {})

    expect(document.querySelector('.people-toast')).toBeNull()
    confirmSpy.mockRestore()
  })

  it('a refused removal leaves the toast alone only if it never started', async () => {
    // The confirm() is the gate: cancelling it must not retire a toast, because nothing happened.
    await mount()
    await raiseToast()
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)

    const removeBtn = [...document.querySelectorAll('.people-row-actions button')]
      .find((b) => b.textContent === 'Remove')
    await act(async () => { removeBtn.click() })
    await act(async () => {})

    expect(document.querySelector('.people-toast')).not.toBeNull()
    expect(removePerson).not.toHaveBeenCalled()
    confirmSpy.mockRestore()
  })

  it('still replaces the toast when ANOTHER role is assigned, rather than leaving none', async () => {
    await mount()
    await raiseToast()

    await act(async () => { setValue(sel('Workspace role for ana@x.com'), '') })
    await act(async () => {})

    const toast = document.querySelector('.people-toast')
    expect(toast).not.toBeNull()
    expect(toast.textContent).toContain('ana@x.com')
  })
})

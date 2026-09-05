/**
 * The Roles screen (PRD §8) and the role change confirmation (§9).
 *
 * WHAT THIS FILE IS FOR, and what it deliberately is not. Every rule it exercises — Owner is not
 * editable, a role in use cannot be deleted, you cannot grant beyond your own ceiling — is
 * ENFORCED SERVER-SIDE and tested in tests/test_workspace_roles_admin.py. Nothing here proves any
 * of them hold. What it proves is that the screen does not invite an administrator to attempt
 * something the server will refuse, and does not silently swallow a refusal when they do.
 *
 * The distinction matters because a UI test that passed would otherwise read as evidence the rule
 * is enforced. It is not. Disabling a button is a courtesy; the refusal is the control.
 *
 * THE ONE CLAIM THAT IS ONLY TESTABLE HERE is the "not enforced yet" notice. An administrator who
 * designs roles, assigns them, and reasonably concludes access is now restricted — while every
 * route still admits everyone — has been misled by a screen that looked finished. Nothing on the
 * server can prevent that; only this notice can.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

let ROLES = { roles: [], enforced: false }
let CATALOG = null
const createWorkspaceRole = vi.fn(async (b) => b)
const updateWorkspaceRole = vi.fn(async (id, b) => b)
const deleteWorkspaceRole = vi.fn(async (id) => ({ deleted: id }))

vi.mock('./api.js', async (importActual) => ({
  ...(await importActual()),
  getWorkspaceRoles: vi.fn(async () => ROLES),
  getRoleCapabilities: vi.fn(async () => CATALOG),
  createWorkspaceRole,
  updateWorkspaceRole,
  deleteWorkspaceRole,
}))

const { default: WorkspaceRoles } = await import('./WorkspaceRoles.jsx')

const CATALOG_FULL = {
  tabs: [
    { key: 'overview', label: 'Overview' },
    { key: 'remediate', label: 'Remediate' },
    { key: 'publish', label: 'Release' },
  ],
  levels: ['hidden', 'view', 'operate'],
  grants: [
    { key: 'reports.export', label: 'Export reports or inventory' },
    { key: 'release.publish', label: 'Publish corrected files' },
    { key: 'roles.manage', label: 'Manage roles' },
  ],
  mine: ['overview.view', 'remediate.view', 'remediate.run', 'remediate.review',
         'release.view', 'reports.export', 'roles.manage'],
  ungoverned_tabs: ['acr', 'graph'],
}

const OWNER_ROLE = {
  id: 'owner', name: 'Owner', description: 'Full access.', is_system: true, is_protected: true,
  version: 1, tabs: { overview: 'operate', remediate: 'operate', publish: 'operate' },
  grants: ['reports.export', 'release.publish', 'roles.manage'], capabilities: [], users: 1,
}
const REVIEWER_ROLE = {
  id: 'remediation-reviewer', name: 'Remediation Reviewer', description: 'Reviews fixes.',
  is_system: true, is_protected: false, version: 3,
  tabs: { overview: 'view', remediate: 'operate', publish: 'view' },
  grants: ['reports.export'], capabilities: [], users: 4,
}
const SPARE_ROLE = {
  id: 'spare', name: 'Spare', description: '', is_system: false, is_protected: false, version: 1,
  tabs: { overview: 'view', remediate: 'hidden', publish: 'hidden' }, grants: [],
  capabilities: [], users: 0,
}

afterEach(() => { unmountAll(); vi.clearAllMocks() })
beforeEach(() => {
  CATALOG = CATALOG_FULL
  ROLES = { roles: [OWNER_ROLE, REVIEWER_ROLE, SPARE_ROLE], enforced: true }
})

const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve() }) }
const click = async (el) => { await act(async () => { el.click() }); await flush() }
const byText = (c, sel, re) => [...c.querySelectorAll(sel)].find((e) => re.test(e.textContent))
const rowFor = (c, name) => [...c.querySelectorAll('.roles-row')].find((r) => r.textContent.includes(name))
const buttonIn = (row, label) => [...row.querySelectorAll('button')].find((b) => b.textContent.trim() === label)

async function mount() {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(WorkspaceRoles)) })
  await flush()
  return container
}

// ── the list ──────────────────────────────────────────────────────────────────

describe('the roles list', () => {
  it('shows every role with how many people hold it', async () => {
    const c = await mount()
    expect(rowFor(c, 'Remediation Reviewer').textContent).toContain('4 users')
    expect(rowFor(c, 'Spare').textContent).toContain('0 users')
  })

  it('summarises tab access so two roles can be compared without opening either', async () => {
    const c = await mount()
    expect(rowFor(c, 'Remediation Reviewer').textContent).toContain('3 tabs')
    expect(rowFor(c, 'Remediation Reviewer').textContent).toContain('2 read-only')
    expect(rowFor(c, 'Spare').textContent).toContain('1 tab')
  })

  it('marks the protected role as protected', async () => {
    const c = await mount()
    expect(rowFor(c, 'Owner').querySelector('.roles-chip').textContent).toBe('Protected')
  })
})

// ── the notice nothing on the server can replace ──────────────────────────────

describe('when roles are not being enforced', () => {
  it('says so, in the place an administrator is designing them', async () => {
    ROLES = {
      ...ROLES,
      enforced: false,
      rollout: { mode: 'observe', next: 'navigation', invalid_mode: null,
                 means: 'Roles are resolved and refusals are recorded, but every user keeps '
                      + "today's access." },
    }
    const c = await mount()
    const note = c.querySelector('.roles-not-enforced')
    expect(note).toBeTruthy()
    expect(note.textContent).toContain('not being enforced')
    expect(note.textContent).toContain('refusals are recorded')
    expect(note.textContent).toContain('navigation')
  })

  it('says what the CURRENT stage does, not one sentence for all of them', async () => {
    // The banner used to name an environment variable and claim nothing changed for anyone. At
    // the `navigation` stage that is false — the tabs ARE hidden — and an administrator reading
    // it would change somebody's access believing they had not. The wording comes from the
    // server so it cannot drift from what the rung actually does.
    ROLES = {
      ...ROLES,
      enforced: false,
      rollout: { mode: 'navigation', next: 'enforce', invalid_mode: null,
                 means: 'Tabs a role does not grant are hidden. The server still allows the calls.' },
    }
    const c = await mount()
    const note = c.querySelector('.roles-not-enforced')
    expect(note.textContent).toContain('still allows the calls')
    expect(note.textContent).not.toContain('nothing changes for anyone')
  })

  it('raises an alert when the stage is misconfigured', async () => {
    // The one configuration that looks identical to a workspace nobody has got to yet: the
    // operator set the variable, believes it took effect, and it did not.
    ROLES = {
      ...ROLES,
      enforced: false,
      rollout: { mode: 'off', next: 'observe', invalid_mode: 'enfoce', means: 'No user is affected.' },
    }
    const c = await mount()
    const alert = c.querySelector('[role="alert"]')
    expect(alert).toBeTruthy()
    expect(alert.textContent).toContain('enfoce')
    expect(alert.textContent).toContain('misconfigured')
  })

  it('does not say it once enforcement is on', async () => {
    const c = await mount()
    expect(c.querySelector('.roles-not-enforced')).toBeNull()
  })
})

// ── what the screen refuses to invite ─────────────────────────────────────────

describe('deleting', () => {
  it('is disabled while anyone holds the role, and says why', async () => {
    // The server refuses this (409, and it names the holders). Offering the button anyway would
    // mean the administrator learns the rule by hitting it.
    const c = await mount()
    const btn = buttonIn(rowFor(c, 'Remediation Reviewer'), 'Delete')
    expect(btn.disabled).toBe(true)
    expect(btn.title).toMatch(/reassign the 4 user/i)
  })

  it('is disabled for the protected role', async () => {
    const c = await mount()
    expect(buttonIn(rowFor(c, 'Owner'), 'Delete').disabled).toBe(true)
  })

  it('is offered for a role nobody holds', async () => {
    const c = await mount()
    expect(buttonIn(rowFor(c, 'Spare'), 'Delete').disabled).toBe(false)
  })
})

describe('the protected role', () => {
  it('opens read-only, and explains why rather than just disabling everything', async () => {
    const c = await mount()
    await click(buttonIn(rowFor(c, 'Owner'), 'View'))
    const drawer = c.querySelector('[role="dialog"]')
    expect(drawer.textContent).toMatch(/cannot be changed/i)
    expect(drawer.textContent).toMatch(/lockout/i)
    expect(drawer.querySelector('input').disabled).toBe(true)
    expect([...drawer.querySelectorAll('button')].map((b) => b.textContent.trim())).not.toContain('Save role')
  })

  it('can still be duplicated — that is what makes it usable as a starting point', async () => {
    const c = await mount()
    expect(buttonIn(rowFor(c, 'Owner'), 'Duplicate').disabled).toBe(false)
  })
})

// ── the drawer renders from the server's catalog ──────────────────────────────

describe('the drawer', () => {
  it('builds its grid from the served catalog, not a copy of the tab list', async () => {
    // Two lists diverging is how a checkbox comes to do nothing — visibly ticked, silently
    // ignored. The catalog here deliberately holds THREE tabs, not the real ten.
    const c = await mount()
    await click(buttonIn(rowFor(c, 'Spare'), 'Edit'))
    const rows = [...c.querySelectorAll('.roles-grid tbody tr')]
    expect(rows.map((r) => r.querySelector('th').textContent)).toEqual(['Overview', 'Remediate', 'Release'])
    expect(rows[0].querySelectorAll('input[type="radio"]')).toHaveLength(3)
  })

  it('preselects the level each tab currently has', async () => {
    const c = await mount()
    await click(buttonIn(rowFor(c, 'Remediation Reviewer'), 'Edit'))
    const checked = [...c.querySelectorAll('.roles-grid input:checked')].map((i) => i.value)
    expect(checked).toEqual(['view', 'operate', 'view'])
  })

  it('disables a permission the administrator does not hold themselves', async () => {
    // PRD §14 refuses this server-side. Disabling it here is so they do not design a role around
    // it and meet the refusal at save time, having already decided what the role is for.
    const c = await mount()
    await click(buttonIn(rowFor(c, 'Spare'), 'Edit'))
    const labels = [...c.querySelectorAll('.roles-grant')]
    const publish = labels.find((l) => l.textContent.includes('Publish corrected files'))
    const exportReports = labels.find((l) => l.textContent.includes('Export reports'))
    expect(publish.querySelector('input').disabled).toBe(true)
    expect(publish.textContent).toMatch(/do not hold this permission yourself/i)
    expect(exportReports.querySelector('input').disabled).toBe(false)
  })

  it('sends the version on an edit, so a stale save is refused rather than winning', async () => {
    const c = await mount()
    await click(buttonIn(rowFor(c, 'Spare'), 'Edit'))
    await click(byText(c, 'button', /^Save role$/))
    expect(updateWorkspaceRole).toHaveBeenCalledWith('spare', expect.objectContaining({ version: 1 }))
  })

  it('creates rather than updates when the role is new', async () => {
    const c = await mount()
    await click(byText(c, 'button', /Create role/))
    const input = c.querySelector('[role="dialog"] input')
    await act(async () => {
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(input, 'Auditor')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await click(byText(c, '[role="dialog"] button', /^Create role$/))
    expect(createWorkspaceRole).toHaveBeenCalledWith(expect.objectContaining({ name: 'Auditor' }))
    expect(updateWorkspaceRole).not.toHaveBeenCalled()
  })

  it('carries the source role through a duplicate', async () => {
    const c = await mount()
    await click(buttonIn(rowFor(c, 'Remediation Reviewer'), 'Duplicate'))
    await click(byText(c, '[role="dialog"] button', /^Create role$/))
    expect(createWorkspaceRole).toHaveBeenCalledWith(
      expect.objectContaining({ duplicate_of: 'remediation-reviewer' }))
  })

  it('warns when a role can publish but cannot see what it publishes', async () => {
    // PRD §5 makes grants independent of tab access, which allows this combination. Warned rather
    // than prevented: the two controls are separate on purpose, and quietly repairing it would
    // make a ticked checkbox do nothing.
    ROLES = { roles: [{ ...SPARE_ROLE, grants: ['release.publish'] }], enforced: true }
    CATALOG = { ...CATALOG_FULL, mine: [...CATALOG_FULL.mine, 'release.publish'] }
    const c = await mount()
    await click(buttonIn(rowFor(c, 'Spare'), 'Edit'))
    expect(c.querySelector('.roles-warn').textContent).toMatch(/cannot see the Release tab/i)
  })
})

// ── refusals are shown, not swallowed ─────────────────────────────────────────

describe('when the server refuses', () => {
  it('shows the reason it gave', async () => {
    // The server's message is the useful one — it names the holders, or the permissions the
    // caller lacks. Replacing it with "could not save" throws away the only actionable part.
    updateWorkspaceRole.mockRejectedValueOnce(new Error('role spare is at version 4, not 1'))
    const c = await mount()
    await click(buttonIn(rowFor(c, 'Spare'), 'Edit'))
    await click(byText(c, 'button', /^Save role$/))
    expect(c.querySelector('[role="status"]').textContent).toContain('version 4')
  })
})


// ── accessibility (this is an accessibility product) ──────────────────────────
//
// The existing wcagAxeMatrix.test.jsx renders Settings on its DEFAULT tab, which is People — so
// it never reaches this screen, and adding a new admin surface without scanning it would leave a
// gap in the very matrix ACP publishes about itself. Same axe configuration and the same jsdom
// exclusions as that file, so a rule excluded there is excluded here for the same stated reason
// and not because it was inconvenient.

const JSDOM_EXCLUDED_RULES = new Set(['color-contrast', 'scrollable-region-focusable'])

async function axeViolations(container) {
  const axe = (await import('axe-core')).default
  const results = await axe.run(container, {
    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] },
  })
  return results.violations.filter((v) => !JSDOM_EXCLUDED_RULES.has(v.id))
}

const fmt = (vs) => vs.map((v) => `[${v.impact}] ${v.id}: ${v.description}\n  ${v.nodes[0]?.html?.slice(0, 140) || ''}`).join('\n\n')

describe('accessibility', () => {
  it('the roles list has no axe violations', async () => {
    const c = await mount()
    const violations = await axeViolations(c)
    expect(violations, fmt(violations)).toHaveLength(0)
  })

  it('the drawer has no axe violations', async () => {
    // The radio grid is the part most likely to fail: a table of unlabelled radios is exactly the
    // shape a screen-reader user cannot operate, which is why each carries an explicit aria-label
    // naming both the tab and the level rather than relying on the row header alone.
    const c = await mount()
    await click(buttonIn(rowFor(c, 'Spare'), 'Edit'))
    const violations = await axeViolations(c)
    expect(violations, fmt(violations)).toHaveLength(0)
  })

  it('every access radio names its tab and its level', async () => {
    // Without this a screen-reader user hears "radio, 1 of 3" three times per row with no way to
    // tell Hidden from Operate. axe does not catch it — the inputs are labelled by the table
    // structure in a way it accepts — so it is asserted directly.
    const c = await mount()
    await click(buttonIn(rowFor(c, 'Spare'), 'Edit'))
    const labels = [...c.querySelectorAll('.roles-grid input')].map((i) => i.getAttribute('aria-label'))
    expect(labels).toContain('Remediate: Operate')
    expect(labels).toContain('Overview: Hidden')
    expect(labels.every(Boolean)).toBe(true)
  })
})

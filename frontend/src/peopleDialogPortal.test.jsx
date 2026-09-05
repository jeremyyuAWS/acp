/**
 * The confirmation dialog has to escape the Settings overlay, or selecting a role does nothing.
 *
 * THE BUG, MEASURED IN CHROMIUM BEFORE IT WAS FIXED. Both PeopleAccess dialogs and the Roles
 * drawer are `position: fixed`, and all three render inside Settings, whose `.setoverlay` sets
 * `backdrop-filter: blur(2px)`. An element with a backdrop-filter becomes the CONTAINING BLOCK
 * for its fixed-position descendants — so `fixed` stopped meaning "relative to the viewport" and
 * started meaning "relative to the settings overlay", which scrolls.
 *
 * With the panel scrolled, the dialog rendered at y=-21 and its scrim at y=-105: above the top of
 * the window, present in the DOM, focusable, and invisible. Since PeopleAccess only WRITES after
 * the confirmation is accepted, the whole feature looked inert — the reported symptom was "the
 * dropdown does not work", and nothing was wrong with the dropdown or with the server.
 *
 * WHY THE EXISTING TESTS ALL PASSED. Every one of them mounts PeopleAccess STANDALONE. The defect
 * only exists when it is a descendant of `.setoverlay`, which is how the app actually renders it
 * and how no test did. peopleRoleAssignment.test.jsx even drives this exact dialog and asserts on
 * its text — correctly, and from a tree the bug cannot occur in.
 *
 * So these tests assert the structural property that survives the fix: the overlay is NOT a
 * descendant of the component's own container. jsdom computes no layout and cannot see the
 * displacement, but it can see the parentage, and the parentage is the fix.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { readFileSync } from 'fs'
import { resolve } from 'path'

let PEOPLE
let ROLES

vi.mock('./api.js', async (importActual) => ({
  ...(await importActual()),
  getPeople: vi.fn(async () => PEOPLE),
  getWorkspaceRoles: vi.fn(async () => ROLES),
  addPerson: vi.fn(), updatePerson: vi.fn(), removePerson: vi.fn(),
  assignWorkspaceRole: vi.fn(async () => ({ person: {} })),
  roleImpact: vi.fn(async () => ({ gains: [], loses: ['remediate.run'], enforced: true })),
}))

const { default: PeopleAccess } = await import('./PeopleAccess.jsx')
const css = readFileSync(resolve(import.meta.dirname, 'styles.css'), 'utf8')

beforeEach(() => {
  PEOPLE = {
    can_manage: true, invite_enabled: false, domains: [],
    people: [{ email: 'jeremy.yu@movateazurelabsv2.onmicrosoft.com', provider: 'microsoft',
               status: 'setup_required', role: 'admin' },
             { email: 'jane@hosp.org', provider: 'google', status: 'access_ready', role: 'user',
               workspace_role_id: 'viewer' }],
  }
  ROLES = { roles: [{ id: 'viewer', name: 'Viewer' }, { id: 'analyst', name: 'Analyst' }],
            enforced: true }
})
afterEach(() => { unmountAll(); vi.clearAllMocks() })

const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve() }) }

async function mount() {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(PeopleAccess)) })
  await flush()
  return container
}

async function pick(container, email, value) {
  const sel = container.querySelector(`select[aria-label="Workspace role for ${email}"]`)
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set.call(sel, value)
    sel.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await flush()
  return sel
}

describe('the role-change dialog escapes its container', () => {
  it('renders outside the component subtree, at document.body', async () => {
    const container = await mount()
    await pick(container, 'jane@hosp.org', 'analyst')

    const dialog = document.querySelector('[aria-labelledby="role-change-title"]')
    expect(dialog, 'the dialog did not open at all').toBeTruthy()
    expect(container.contains(dialog)).toBe(false)      // the whole point
    expect(document.body.contains(dialog)).toBe(true)
  })

  it('its fixed scrim is a direct child of body, so nothing can become its containing block',
    async () => {
      // A `position: fixed` element resolves against the viewport ONLY while no ancestor has a
      // transform, filter, backdrop-filter, perspective, contain:paint or will-change. Being a
      // direct child of body is the one arrangement where that cannot be violated by a component
      // rendered somewhere above it.
      const container = await mount()
      await pick(container, 'jane@hosp.org', 'analyst')
      const dialog = document.querySelector('[aria-labelledby="role-change-title"]')
      expect(dialog.parentElement.parentElement).toBe(document.body)
    })

  it('still shows the impact the server computed', async () => {
    // The fix must not cost the content. Portalled children keep React context and props.
    const container = await mount()
    await pick(container, 'jane@hosp.org', 'analyst')
    const dialog = document.querySelector('[aria-labelledby="role-change-title"]')
    expect(dialog.textContent).toContain('remediate.run')
    expect(dialog.textContent).toContain('Analyst')
  })
})

describe('the add-person dialog escapes too', () => {
  it('renders at document.body, not inside the People section', async () => {
    // Same file, same trap, same screen — it opens from the button right above the dialog that
    // was reported. Fixing one and not the other would leave the bug alive one click away.
    const container = await mount()
    const add = [...container.querySelectorAll('button')].find((b) => /add people/i.test(b.textContent))
    await act(async () => { add.click() })
    await flush()
    const dialog = document.querySelector('[aria-labelledby="add-person-title"]')
    expect(dialog).toBeTruthy()
    expect(container.contains(dialog)).toBe(false)
    expect(document.body.contains(dialog)).toBe(true)
  })
})

describe('the trap this guards against is still present in the stylesheet', () => {
  it('.setoverlay really does carry a backdrop-filter', () => {
    // THE PREMISE, ASSERTED. If somebody removes the blur, these portals stop being load-bearing
    // and this file should be re-read rather than left implying a danger that is gone. If it is
    // still there, the portals are the only thing standing between a scrolled panel and an
    // invisible dialog.
    const rule = css.match(/\.setoverlay\s*\{[^}]+\}/)
    expect(rule).not.toBeNull()
    expect(rule[0]).toContain('backdrop-filter')
    expect(rule[0]).toContain('overflow-y: auto')
  })
})

describe('the two selects are styled like the rest of the app', () => {
  it('both carry the shared class rather than browser defaults', async () => {
    const container = await mount()
    const selects = [...container.querySelectorAll('select')]
    expect(selects.length).toBeGreaterThan(0)
    for (const s of selects) expect(s.className).toContain('people-select')
  })

  it('an unassigned role reads as muted, an assigned one does not', async () => {
    const container = await mount()
    const unassigned = container.querySelector(
      'select[aria-label="Workspace role for jeremy.yu@movateazurelabsv2.onmicrosoft.com"]')
    const assigned = container.querySelector('select[aria-label="Workspace role for jane@hosp.org"]')
    expect(unassigned.className).toContain('is-unassigned')
    expect(assigned.className).not.toContain('is-unassigned')
  })

  it('a long address can wrap instead of painting over the badge beside it', async () => {
    // Grid items have `min-width: auto`, so before this the 43-character tenant address held its
    // cell at full text width and overlapped the status chip. Real addresses are what exposed it;
    // the short fixtures elsewhere in this suite never could.
    const container = await mount()
    const email = container.querySelector('.people-email')
    expect(email.textContent).toBe('jeremy.yu@movateazurelabsv2.onmicrosoft.com')
    expect(css).toMatch(/\.people-row > \*\s*\{[^}]*min-width:\s*0/)
    expect(css).toMatch(/\.people-email\s*\{[^}]*overflow-wrap:\s*anywhere/)
  })
})

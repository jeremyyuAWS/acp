/**
 * The People row: one grid track per cell, and a badge that is a badge.
 *
 * TWO BUGS, BOTH FOUND BY LOOKING AT THE RUNNING APP RATHER THAN AT THE CODE, and both invisible
 * to every existing test because the suite asserts on ROLES AND TEXT, never on geometry.
 *
 * 1. The row declared FOUR grid tracks —
 *      'minmax(210px,1.5fr) 110px 140px minmax(180px,1fr)'
 *    — and rendered FIVE cells whenever workspace roles existed, because the workspace-role
 *    column was added later without widening the template. Grid put the fifth cell (Suspend /
 *    Remove) on an implicit SECOND ROW at column 1, under the email address. Measured in
 *    Chromium: 4 tracks, 5 children, the actions cell at x=57 y=364 while the rest sat at y≈320.
 *
 * 2. The status badge set `display: inline-block` to make a pill that hugs its label, but it was
 *    a DIRECT grid child, and grid items are blockified — computed `display: block`, width 110px.
 *    The tint rendered as a band across the whole column instead of a pill.
 *
 * WHY THESE ARE UNIT TESTS AND NOT SCREENSHOTS. jsdom computes no layout, so neither bug can be
 * observed here directly. What CAN be asserted is the thing that caused both: the number of grid
 * cells the component emits versus the number of tracks its class declares, and whether the badge
 * is a direct grid child. Those are the facts that broke — the pixels were the symptom.
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
  roleImpact: vi.fn(async () => ({ gains: [], loses: [], enforced: true })),
}))

const { default: PeopleAccess } = await import('./PeopleAccess.jsx')

const css = readFileSync(resolve(import.meta.dirname, 'styles.css'), 'utf8')

beforeEach(() => {
  PEOPLE = {
    can_manage: true, invite_enabled: false, domains: [],
    people: [
      { email: 'alice@hosp.org', provider: 'google', status: 'access_ready', role: 'user' },
      { email: 'dan@hosp.org', provider: 'google', status: 'suspended', role: 'user' },
    ],
  }
  ROLES = { roles: [{ id: 'viewer', name: 'Viewer' }], enforced: true }
})

afterEach(() => { unmountAll(); vi.clearAllMocks() })

const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve() }) }

async function mount() {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(PeopleAccess)) })
  await flush()
  return container
}

// Read the track list a class declares, so the assertion is against the SHIPPED css rather than
// a number copied into this file that could drift from it.
function tracksFor(selector) {
  const rule = css.match(new RegExp(`${selector.replace(/\./g, '\\.')}\\s*\\{([^}]+)\\}`))
  expect(rule, `no rule for ${selector}`).not.toBeNull()
  const decl = rule[1].match(/grid-template-columns:\s*([^;]+);/)
  expect(decl, `${selector} declares no grid-template-columns`).not.toBeNull()
  // minmax(a, b) counts as ONE track — collapse it before splitting on whitespace.
  return decl[1].replace(/minmax\([^)]*\)/g, 'X').trim().split(/\s+/).filter(Boolean)
}

describe('the row has exactly as many grid tracks as it has cells', () => {
  it('five cells and five tracks when workspace roles exist', async () => {
    const c = await mount()
    const row = c.querySelector('.people-row')
    expect(row.classList.contains('has-role-column')).toBe(true)
    expect(row.children.length).toBe(5)
    expect(tracksFor('.people-row.has-role-column')).toHaveLength(5)
  })

  it('four cells and four tracks when no roles are defined', async () => {
    // The workspace-role cell is conditional, so the template has to be too — a five-track row
    // holding four cells leaves a gap where nothing is, which is the same class of mistake in
    // the other direction.
    ROLES = { roles: [], enforced: true }
    const c = await mount()
    const row = c.querySelector('.people-row')
    expect(row.classList.contains('has-role-column')).toBe(false)
    expect(row.children.length).toBe(4)
    expect(tracksFor('.people-row')).toHaveLength(4)
  })

  it('the actions cell is the last child, so it lands in the last track', async () => {
    // What actually went wrong: the actions cell overflowed onto a second row. Its being last is
    // what puts it under the right-hand track rather than wrapping.
    const c = await mount()
    const row = c.querySelector('.people-row')
    expect(row.lastElementChild.className).toBe('people-row-actions')
  })
})

describe('the status badge', () => {
  it('is wrapped, so it is not a direct grid child and keeps inline-block', async () => {
    // The whole bug in one assertion: a direct grid child is blockified and the pill becomes a
    // full-width band. The wrapper takes the grid slot; the badge sits inside it.
    const c = await mount()
    const badge = c.querySelector('.people-badge')
    expect(badge).toBeTruthy()
    expect(badge.parentElement.className).toBe('people-badge-cell')
    expect(badge.parentElement.parentElement.classList.contains('people-row')).toBe(true)
  })

  it('carries a status class rather than an inline colour', async () => {
    const c = await mount()
    const badges = [...c.querySelectorAll('.people-badge')]
    expect(badges.map((b) => b.className)).toEqual([
      'people-badge is-access_ready', 'people-badge is-suspended',
    ])
    expect(badges.every((b) => !b.getAttribute('style'))).toBe(true)
  })

  it('an unrecognised status falls back to the neutral class and shows the raw value', async () => {
    // The old code had a hex fallback for this; it has to keep rendering something legible
    // rather than an unstyled word.
    PEOPLE.people = [{ email: 'x@hosp.org', provider: 'google', status: 'quarantined' }]
    const c = await mount()
    const badge = c.querySelector('.people-badge')
    expect(badge.className).toBe('people-badge is-unknown')
    expect(badge.textContent).toBe('quarantined')
  })
})

describe('badge colours come from the semantic tokens', () => {
  // styles.css centralises --success/--warn/--info/--error precisely so [data-wcag="on"] can
  // tighten them in one place. These states had hex literals instead — all of them passing AA,
  // so this is drift rather than a contrast defect, but `active` was using a green measured at
  // 4.72:1 where the app's own audited pair gives 7.56:1.
  const rule = (sel) => {
    const m = css.match(new RegExp(`${sel.replace(/[.\\]/g, '\\$&')}[^{]*\\{([^}]+)\\}`))
    expect(m, `no rule for ${sel}`).not.toBeNull()
    return m[1]
  }

  it.each([
    ['.people-badge.is-invited', '--info-fg', '--info-bg'],
    ['.people-badge.is-setup_required', '--warn-fg', '--warn-bg'],
    ['.people-badge.is-failed', '--error-fg-strong', '--error-bg'],
  ])('%s uses %s / %s', (sel, fg, bg) => {
    const body = rule(sel)
    expect(body).toContain(`var(${fg})`)
    expect(body).toContain(`var(${bg})`)
  })

  it('the success pair covers both active and access_ready', () => {
    const body = rule('.people-badge.is-access_ready')
    expect(body).toContain('var(--success-fg-strong)')
    expect(body).toContain('var(--success-bg)')
    expect(css).toContain('.people-badge.is-active,')
  })

  it('no badge rule hard-codes a hex colour', () => {
    // The regression guard. wcagCssVariableUsage.test.jsx scans this file for named selectors;
    // this is the same idea for the family added here, so a literal cannot creep back in.
    const badgeRules = css.match(/\.people-badge\.is-[a-z_,\s.-]*\{[^}]+\}/g) || []
    expect(badgeRules.length).toBeGreaterThan(0)
    for (const r of badgeRules) expect(r).not.toMatch(/#[0-9a-fA-F]{3,8}/)
  })
})

describe('the two advisory notes share one rule', () => {
  it('the domain note is a class, not six inline declarations', async () => {
    // They render identically and sit one above the other; they differed only in how they were
    // built, which is how two things that must look alike drift apart.
    PEOPLE.domains = ['hosp.org']
    const c = await mount()
    const note = c.querySelector('.people-domain-note')
    expect(note).toBeTruthy()
    expect(note.getAttribute('style')).toBeNull()
    expect(css).toMatch(/\.roles-not-enforced,\s*\n?\.people-domain-note/)
  })
})

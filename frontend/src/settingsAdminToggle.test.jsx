/**
 * The owner-only "Make admin" control in Settings → Users.
 *
 * Multi-admin (ACP_ADMIN_EMAILS + owner-managed set) lets more than one person be a Platform Admin.
 * This pins the UI half: the owner sees a promote/demote toggle on ordinary users and clicking it
 * calls setAdmins; an env-admin shows a permanent (non-editable) badge; the owner has no toggle on
 * themselves; and a NON-owner admin sees no toggle at all (managing admins is owner-only, enforced
 * server-side too).
 */
import { describe, it, expect, afterEach, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const setAdmins = vi.fn((emails) => Promise.resolve({ owner: 'owner@hosp.org', env_admins: ['env@hosp.org'], admins: emails }))
let ME = { is_owner: true }

vi.mock('./api.js', () => ({
  getAllowlist: () => Promise.resolve({ emails: ['deva@hosp.org', 'env@hosp.org', 'owner@hosp.org'], owner: 'owner@hosp.org', domains: [], invite_enabled: false }),
  getAdmins: () => Promise.resolve({ owner: 'owner@hosp.org', env_admins: ['env@hosp.org'], admins: [] }),
  setAdmins,
  getMe: () => Promise.resolve(ME),
  setAllowlist: () => Promise.resolve({ emails: [] }),
  inviteTester: () => Promise.resolve({}),
}))

afterEach(() => { unmountAll(); setAdmins.mockClear(); ME = { is_owner: true } })

const { AllowList } = await import('./Settings.jsx')

const settle = async (ms = 60) => {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
  for (let k = 0; k < 3; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}
const render = async () => {
  const { container } = createTestRoot()
  const { createRoot } = await import('react-dom/client')
  const host = document.createElement('div'); container.appendChild(host)
  const root = createRoot(host)
  await act(async () => { root.render(createElement(AllowList)) })
  await settle()
  return container
}
const btn = (c, label) => [...c.querySelectorAll('button')].find((b) => b.textContent.trim() === label)

describe('owner-only admin promotion in Settings → Users', () => {
  it('the owner sees "Make admin" on an ordinary user and clicking it calls setAdmins', async () => {
    const c = await render()
    const make = [...c.querySelectorAll('button')].filter((b) => b.textContent.trim() === 'Make admin')
    // deva (ordinary) gets a toggle; owner and env-admin do not.
    expect(make.length).toBe(1)
    await act(async () => { make[0].click() })
    await settle()
    expect(setAdmins).toHaveBeenCalledWith(['deva@hosp.org'])
  })

  it('an env-admin shows a permanent badge and is not editable', async () => {
    const c = await render()
    expect(c.textContent).toContain('admin · set at deploy')
    // Only ONE promote toggle exists (deva's) — the env-admin and owner rows have none, so the
    // permanent grant can't be demoted here.
    expect([...c.querySelectorAll('button')].filter((b) => /^(Make|Remove) admin$/.test(b.textContent.trim())).length).toBe(1)
  })

  it('a non-owner sees no promote/demote controls at all', async () => {
    ME = { is_owner: false }
    const c = await render()
    expect(btn(c, 'Make admin')).toBeUndefined()
    expect(btn(c, 'Remove admin')).toBeUndefined()
  })
})

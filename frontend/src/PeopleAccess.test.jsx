import { afterEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react-dom/test-utils'
import { createElement } from 'react'
import axe from 'axe-core'
import { createTestRoot, unmountAll } from './testRoots.js'

const getPeople = vi.fn(() => Promise.resolve({
  people: [
    { email: 'owner@hosp.org', provider: 'google', role: 'owner', status: 'active', protected: true },
    { email: 'guest@hosp.org', provider: 'microsoft', role: 'user', status: 'setup_required' },
  ], invite_enabled: false, domains: ['hosp.org'], can_manage: true,
}))
const addPerson = vi.fn((person) => Promise.resolve({ person: { ...person, status: 'access_ready' } }))
const updatePerson = vi.fn((email, patch) => Promise.resolve({ person: { email, provider: 'microsoft', role: 'user', ...patch } }))
const removePerson = vi.fn(() => Promise.resolve({ people: [] }))
vi.mock('./api.js', () => ({ getPeople, addPerson, updatePerson, removePerson }))

const PeopleAccess = (await import('./PeopleAccess.jsx')).default
afterEach(() => { unmountAll(); vi.clearAllMocks() })
const settle = async () => { for (let i = 0; i < 3; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
async function render() {
  const { container } = createTestRoot()
  const { createRoot } = await import('react-dom/client')
  const host = document.createElement('div'); container.appendChild(host)
  const root = createRoot(host)
  await act(async () => root.render(createElement(PeopleAccess)))
  await settle()
  return container
}

describe('People access onboarding', () => {
  it('shows provider-aware status, domain access, and protected owner', async () => {
    const c = await render()
    expect(c.textContent).toContain('Domain-wide access is on')
    expect(c.textContent).toContain('Setup needed')
    expect(c.textContent).toContain('Invite in Entra')
    expect(c.textContent).toContain('Owner')
    expect([...c.querySelectorAll('button')].filter((b) => b.textContent === 'Remove')).toHaveLength(1)
  })

  it('uses one dialog for either provider and returns focus when cancelled', async () => {
    const c = await render()
    const add = [...c.querySelectorAll('button')].find((b) => b.textContent.includes('Add people'))
    await act(async () => add.click())
    expect(c.querySelector('[role="dialog"]')).not.toBeNull()
    expect(document.activeElement.getAttribute('placeholder')).toBe('name@company.com')
    const microsoft = c.querySelector('input[value="microsoft"]')
    await act(async () => microsoft.click())
    expect(c.textContent).toContain('Microsoft guest invitations are not connected')
    await act(async () => [...c.querySelectorAll('button')].find((b) => b.textContent === 'Cancel').click())
    await settle()
    expect(document.activeElement).toBe(add)
  })

  it('has no automated accessibility violations with the onboarding dialog open', async () => {
    const c = await render()
    await act(async () => [...c.querySelectorAll('button')].find((b) => b.textContent.includes('Add people')).click())
    const result = await axe.run(c, { rules: { region: { enabled: false } } })
    expect(result.violations).toEqual([])
  })

  it('submits the chosen identity provider and honest role', async () => {
    const c = await render()
    await act(async () => [...c.querySelectorAll('button')].find((b) => b.textContent.includes('Add people')).click())
    const email = c.querySelector('input[type="email"]')
    const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    await act(async () => { setValue.call(email, 'new@example.com'); email.dispatchEvent(new Event('input', { bubbles: true })) })
    await act(async () => c.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
    await settle()
    expect(addPerson).toHaveBeenCalledWith({ email: 'new@example.com', provider: 'google', role: 'user' })
  })
})

/**
 * Settings is scoped to access management (Owners + Users) plus the one self-service action every
 * signed-in user needs (My Data — reset only your own scans; see resetMyData.test.jsx).
 *
 * The six OTHER admin panels (Scoring rules, Estate, File types, Remediated storage, Disposition,
 * the global admin Data reset, AI-provider governance) were removed from the tab bar on request.
 * They were NOT deleted — their components are still exported from Settings.jsx and still covered
 * by their own tests (see simAdminWriteHonesty / aiProviders / aiEndpointSettings). This test pins
 * both halves: those six are gone, and the code that could bring one back is still here.
 *
 * It also covers the Users-tab onboarding: two equal paths, Microsoft (SharePoint/OneDrive) and
 * Google (Drive), each ending at the same allowlist.
 */
import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const { default: Settings, ResetData, DriveMirror, AIProvidersPanel } = await import('./Settings.jsx')

const settle = async (ms = 340) => {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)) })
  for (let k = 0; k < 3; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}
const render = async () => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(Settings, { onClose: () => {} })) })
  await settle()
  return container
}
const tabTexts = (c) => [...c.querySelectorAll('button[role="tab"]')].map((b) => b.textContent.trim())
const setValue = (el, v) => {
  const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  set.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true }))
}

describe('the settings panel is access-only, plus self-service My Data and My Scope', () => {
  it('shows exactly the Owners, Users, My Data and My Scope tabs, in that order', async () => {
    expect(tabTexts(await render())).toEqual(['Owners', 'Users', 'My Data', 'My Scope'])
  })

  it('no longer offers any of the removed ADMIN-ONLY tabs', async () => {
    const texts = tabTexts(await render())
    for (const gone of ['Scoring rules', 'Estate', 'File types', 'Remediated storage', 'Disposition', 'Data']) {
      expect(texts).not.toContain(gone)
    }
  })

  it('opens on the Users tab', async () => {
    const c = await render()
    expect(c.querySelector('button[role="tab"][aria-selected="true"]').textContent.trim()).toBe('Users')
  })
})

describe('the removed panels are hidden, not deleted', () => {
  it('still exports the three local admin panels so their features and guards survive', () => {
    expect(typeof ResetData).toBe('function')
    expect(typeof DriveMirror).toBe('function')
    expect(typeof AIProvidersPanel).toBe('function')
  })
})

describe('the Users tab onboards Microsoft and Google testers equally', () => {
  it('renders both a Microsoft and a Google onboarding card', async () => {
    const c = await render()
    expect(c.textContent).toContain('Microsoft')
    expect(c.textContent).toContain('Google')
    // The Google card whitelists a Gmail; the OAuth-consent test-user step is surfaced too.
    expect([...c.querySelectorAll('button')].some((b) => b.textContent.trim() === 'Whitelist')).toBe(true)
    expect(c.querySelector('a[href*="console.cloud.google.com/apis/credentials/consent"]')).toBeTruthy()
  })

  it('whitelisting a Google tester persists it to the list', async () => {
    const c = await render()
    const input = c.querySelector('input[aria-label="Whitelist a Google tester by email"]')
    expect(input).toBeTruthy()
    setValue(input, 'newtester@gmail.com')
    const btn = [...c.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Whitelist')
    await act(async () => { btn.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    await settle()
    expect(c.textContent).toContain('Whitelisted newtester@gmail.com')
    expect(c.textContent).toContain('newtester@gmail.com')
  })
})

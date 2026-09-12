import { createElement, act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import { isVisible, canOperate, isViewOnly } from './access.js'
const tabs = ['overview','integrations','discover','assess','remediate','publish','monitor','liveops','analytics','graph','acr','settings']
const role = { id: 'platform-admin', name: 'Platform Admin', version: 1, tabs: Object.fromEntries(tabs.map(k => [k,'operate'])), grants: ['roles.manage'], users: 7 }
const api = vi.hoisted(() => ({ getWorkspaceRoles: vi.fn(), getRoleCapabilities: vi.fn(), updateWorkspaceRole: vi.fn(), createWorkspaceRole: vi.fn(), deleteWorkspaceRole: vi.fn(), putRoleEnforcement: vi.fn(), getWorkspaceRolePreflight: vi.fn(), bootstrapWorkspaceRoles: vi.fn() }))
vi.mock('./api.js', () => api)
import WorkspaceRoles from './WorkspaceRoles.jsx'
afterEach(async () => { await unmountAll(); vi.clearAllMocks() })
it('honors Hidden, View, and Operate for every current tab', () => {
  for (const key of tabs) for (const level of ['hidden','view','operate']) {
    const access = { enforced: true, tabs: { [key]: level } }
    expect(isVisible(access, key), `${key} ${level}`).toBe(level !== 'hidden')
    expect(canOperate(access, key), `${key} ${level}`).toBe(level === 'operate')
    expect(isViewOnly(access, key), `${key} ${level}`).toBe(level === 'view')
  }
})
it('refreshes active-session access immediately after saving Conformance as Hidden', async () => {
  api.getWorkspaceRoles.mockResolvedValue({ roles: [role], enforced: true, rollout: { mode: 'enforce' } })
  api.getRoleCapabilities.mockResolvedValue({ tabs: tabs.map(key => ({ key, label: key === 'acr' ? 'Conformance' : key })), levels: ['hidden','view','operate'], grants: [], mine: ['roles.manage'] })
  api.updateWorkspaceRole.mockResolvedValue({ ...role, version: 2, tabs: { ...role.tabs, acr: 'hidden' } })
  const refresh = vi.fn()
  window.addEventListener('acp-access-changed', refresh)
  try {
    const { root, container } = createTestRoot()
    await act(async () => { root.render(createElement(WorkspaceRoles)); await Promise.resolve() })
    const edit = [...container.querySelectorAll('button')].find(b => b.textContent === 'Edit')
    await act(async () => { edit.click() })
    await act(async () => { document.querySelector('[aria-label="Conformance: Hidden"]').click() })
    await act(async () => { [...document.querySelectorAll('button')].find(b => b.textContent === 'Save role').click(); await Promise.resolve() })
    expect(api.updateWorkspaceRole).toHaveBeenCalledWith('platform-admin', expect.objectContaining({ tabs: expect.objectContaining({ acr: 'hidden' }) }))
    expect(refresh).toHaveBeenCalledTimes(1)
  } finally { window.removeEventListener('acp-access-changed', refresh) }
})

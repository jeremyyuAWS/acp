import { act, createElement } from 'react'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import SharePointScopePicker, { matchingLocation } from './SharePointScopePicker.jsx'
import { CUSTOMER_SHAREPOINT_URL } from './sharepointDestination.js'
import { listSharePointSites, listSharePointDrives, listSpFolders } from './api.js'

vi.mock('./api.js', () => ({
  listSharePointSites: vi.fn(), listSharePointDrives: vi.fn(), listSpFolders: vi.fn(),
  listFolders: vi.fn(), getConfig: vi.fn(async () => ({ sharepoint_max_sites: 30 })),
}))
beforeEach(() => {
  listSharePointSites.mockResolvedValue({ sites: [
    { id: 'other', name: 'Communication site', url: 'https://other.sharepoint.com' },
    { id: 'communication', name: 'Communication site', url: 'https://fgxlxj.sharepoint.com/' },
  ] })
  listSharePointDrives.mockResolvedValue({ drives: [
    { id: 'policies', name: 'Policies', url: 'https://fgxlxj.sharepoint.com/Policies' },
    { id: 'documents', name: 'Documents', url: 'https://fgxlxj.sharepoint.com/Shared%20Documents' },
  ] })
  listSpFolders.mockResolvedValue({ folders: [{ id: 'documents/clinical', name: 'Clinical Shared Drive' }] })
})
afterEach(async () => { await unmountAll(); vi.clearAllMocks() })
async function mount(props = {}) {
  const view = createTestRoot()
  await act(async () => { view.root.render(createElement(SharePointScopePicker, { layout: 'inline', ...props })) })
  return view.container
}

it('opens the linked library and selects qualified folders rather than the whole site', async () => {
  const changed = vi.fn()
  const host = await mount({ onChange: changed })
  expect(listSharePointDrives).toHaveBeenCalledWith('communication')
  expect(listSpFolders).toHaveBeenCalledWith('root', 'documents', 'communication')
  expect(host.textContent).toContain('Communication site → Documents')
  expect(host.textContent).toContain('Clinical Shared Drive')
  expect(host.querySelector('a').href).toBe(CUSTOMER_SHAREPOINT_URL)
  expect(host.querySelector('input[type="checkbox"]').checked).toBe(false)
  await act(async () => host.querySelector('input[type="checkbox"]').click())
  expect(changed).toHaveBeenLastCalledWith([{ id: 'documents/clinical', name: 'Clinical Shared Drive' }], [])
})

it('preserves saved site selection instead of switching it into a library', async () => {
  const host = await mount({ initial: [{ id: 'communication', name: 'Communication site' }], onChange: vi.fn() })
  expect(host.querySelector('.sp-picker')).not.toBeNull()
  expect(listSpFolders).not.toHaveBeenCalled()
  expect(host.textContent).toContain('1 SharePoint site selected')
})

it('does not fall back to OneDrive when the linked site is inaccessible', async () => {
  listSharePointSites.mockResolvedValue({ sites: [] })
  const host = await mount({ onChange: vi.fn() })
  expect(host.querySelector('[role="alert"]').textContent).toContain('not available to this sign-in')
  expect(listSpFolders).not.toHaveBeenCalled()
  await act(async () => [...host.querySelectorAll('button')].find(b => b.textContent === 'Browse other sites').click())
  expect(host.querySelector('.sp-picker')).not.toBeNull()
})

it('matches HTTPS URL boundaries and prefers the deepest matching library', () => {
  const rows = [{ id: 'wrong', url: 'https://fgxlxj.sharepoint.com/Shared' },
    { id: 'root', url: 'https://fgxlxj.sharepoint.com/' },
    { id: 'library', url: 'https://fgxlxj.sharepoint.com/Shared Documents/' }]
  expect(matchingLocation(rows, CUSTOMER_SHAREPOINT_URL).id).toBe('library')
  expect(matchingLocation(rows, 'http://fgxlxj.sharepoint.com/Shared Documents')).toBeNull()
})

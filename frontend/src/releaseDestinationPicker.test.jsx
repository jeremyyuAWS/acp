import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ReleaseDestinationPicker from './ReleaseDestinationPicker.jsx'

const api = vi.hoisted(() => ({
  listFolders: vi.fn(async () => ({ folders: [{ id: 'finance', name: 'Finance' }] })),
  listSpFolders: vi.fn(async () => ({ folders: [] })),
  listSharePointSites: vi.fn(async () => ({ sites: [] })),
  listSharePointDrives: vi.fn(async () => ({ drives: [] })),
  putMyReleaseDestination: vi.fn(async (value) => ({ release_destination: value })),
}))
vi.mock('./api.js', () => api)

let node
afterEach(() => { node?.remove(); node = null; vi.clearAllMocks() })

async function mount(props = {}) {
  node = document.createElement('div'); document.body.appendChild(node)
  await act(async () => createRoot(node).render(<ReleaseDestinationPicker provider="drive" {...props} />))
  return node
}

describe('Release destination picker', () => {
  it('starts with an honest provider default and opens the established folder browser', async () => {
    const view = await mount()
    expect(view.textContent).toContain('Default “Remediated” folder in Google Drive')
    await act(async () => view.querySelector('button').click())
    await act(async () => {})
    expect(view.textContent).toContain('Choose a Release folder in Google Drive')
    expect(view.textContent).toContain('Finance')
    expect(view.textContent).not.toContain('Scan all')
  })

  it('persists one stable folder id and label, then reports the saved value', async () => {
    const onChange = vi.fn()
    const view = await mount({ onChange })
    await act(async () => view.querySelector('button').click())
    await act(async () => {})
    const checkbox = view.querySelector('input[type="checkbox"]')
    await act(async () => checkbox.click())
    const save = [...view.querySelectorAll('button')].find((button) => button.textContent === 'Use this folder')
    await act(async () => save.click())
    const expected = { provider: 'drive', folder_id: 'finance', folder_name: 'Finance' }
    expect(api.putMyReleaseDestination).toHaveBeenCalledWith(expected)
    expect(onChange).toHaveBeenCalledWith(expected)
  })
})


it('browses a SharePoint destination when personal OneDrive returns 404', async () => {
  api.listSpFolders.mockImplementation(async parent => {
    if (parent === 'root') throw Object.assign(new Error('no document library found for that site or user'), { status: 404 })
    return { folders: [{ id: 'team-drive/folder', name: 'Outputs' }] }
  })
  api.listSharePointSites.mockResolvedValue({ sites: [{ id: 'team-site', name: 'Team' }] })
  api.listSharePointDrives.mockResolvedValue({ drives: [{ id: 'team-drive', name: 'Documents' }] })
  const onChange = vi.fn()
  const view = await mount({ provider: 'sharepoint', onChange })
  const clickText = async text => { await act(async () => [...view.querySelectorAll('button')].find(b => b.textContent.includes(text)).click()) }
  await clickText('Choose folder')
  expect(view.textContent).not.toContain('We couldn’t load')
  expect(view.querySelector('input[type="checkbox"]')).toBeNull()
  await clickText('SharePoint · Team')
  expect(api.listSharePointDrives).toHaveBeenCalledWith('team-site')
  expect(view.querySelector('input[type="checkbox"]')).toBeNull()
  await clickText('Documents')
  expect(api.listSpFolders).toHaveBeenCalledWith('team-drive/root')
  await act(async () => view.querySelector('input[type="checkbox"]').click())
  await clickText('Use this folder')
  expect(onChange).toHaveBeenCalledWith({ provider: 'sharepoint', folder_id: 'team-drive/folder', folder_name: 'Outputs' })
})

import { beforeEach, expect, it, vi } from 'vitest'
import { listSpFolders, listSharePointSites, listSharePointDrives } from './api.js'
import { listReleaseMicrosoftFolders } from './releaseFolderBrowser.js'
vi.mock('./api.js', () => ({ listSpFolders: vi.fn(), listSharePointSites: vi.fn(), listSharePointDrives: vi.fn() }))
beforeEach(() => vi.resetAllMocks())
it('keeps personal folders available when site enumeration is not permitted', async () => {
  listSpFolders.mockResolvedValue({ folders: [{ id: 'personal/folder', name: 'Work' }] })
  listSharePointSites.mockRejectedValue(Object.assign(new Error('forbidden'), { status: 403 }))
  expect(await listReleaseMicrosoftFolders()).toEqual({ folders: [{ id: 'personal/folder', name: 'Work' }] })
})
it('reports an actual loading failure instead of claiming an empty directory', async () => {
  listSpFolders.mockRejectedValue(Object.assign(new Error('missing library'), { status: 404 }))
  listSharePointSites.mockRejectedValue(Object.assign(new Error('forbidden'), { status: 403 }))
  await expect(listReleaseMicrosoftFolders()).rejects.toThrow('403: forbidden')
})
it('passes real nested drive/item ids through unchanged', async () => {
  listSpFolders.mockResolvedValue({ folders: [] })
  await listReleaseMicrosoftFolders('drive/item')
  expect(listSpFolders).toHaveBeenCalledWith('drive/item')
  expect(listSharePointSites).not.toHaveBeenCalled()
})

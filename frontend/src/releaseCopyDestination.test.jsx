import { act, createElement } from 'react'
import { afterEach, expect, it } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import ReleaseCopyDestination from './ReleaseCopyDestination.jsx'
afterEach(unmountAll)
async function mount(props) {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(ReleaseCopyDestination, props)))
  return container
}
it('shows the timestamp subfolder before SharePoint publication without inventing a link', async () => {
  const c = await mount({ provider: 'sharepoint', destination: { folder_name: 'Policies' } })
  expect(c.textContent).toContain('SharePoint / Policies / Remediated / Release date and time')
  expect(c.textContent).toContain('original documents stay unchanged')
  expect(c.querySelector('a')).toBeNull()
  expect(c.querySelector('section').closest('[hidden]')).toBeNull()
})
it('links to the actual durable release folder and preserves custom names', async () => {
  const c = await mount({ provider: 'sharepoint', folderName: 'Ignored draft', folder: { name: '2026-09-09 15-00 PDT', url: 'https://example.sharepoint.com/release' } })
  expect(c.textContent).toContain('2026-09-09 15-00 PDT')
  expect(c.textContent).not.toContain('Ignored draft')
  expect(c.querySelector('a').getAttribute('href')).toBe('https://example.sharepoint.com/release')
})
it('exposes every library destination and makes no SharePoint promise for managed storage', async () => {
  const c = await mount({ provider: 'sharepoint', folders: [{ id: 'a', url: 'https://sp/a' }, { id: 'b', url: 'https://sp/b' }] })
  expect(c.querySelectorAll('a')).toHaveLength(2)
  const managed = await mount({ provider: 'upload' })
  expect(managed.textContent).toBe('')
})

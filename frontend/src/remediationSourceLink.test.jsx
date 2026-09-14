import { afterEach, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
vi.mock('./api.js',()=>({getSourceLink:vi.fn()}))
import { getSourceLink } from './api.js'
import RemediationSourceLink from './RemediationSourceLink.jsx'
afterEach(()=>{unmountAll();vi.resetAllMocks()})
it('opens the exact provider document returned by the owner-scoped source lookup', async()=>{
  getSourceLink.mockResolvedValue({url:'https://tenant.sharepoint.com/document.docx',label:'Open in SharePoint'})
  const {root,container}=createTestRoot()
  await act(async()=>root.render(createElement(RemediationSourceLink,{finding:{scanId:'scan',file:'document.docx'}})))
  expect(getSourceLink).toHaveBeenCalledWith('scan','document.docx')
  expect(container.querySelector('a').href).toBe('https://tenant.sharepoint.com/document.docx')
})
it('does not invent a source link when provider lookup cannot find one', async()=>{
  getSourceLink.mockResolvedValue({url:null})
  const {root,container}=createTestRoot()
  await act(async()=>root.render(createElement(RemediationSourceLink,{finding:{scanId:'scan',file:'document.docx'}})))
  expect(container.querySelector('a')).toBeNull()
})

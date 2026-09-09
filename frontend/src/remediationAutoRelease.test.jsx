import { act, createElement } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationAutoRelease from './RemediationAutoRelease.jsx'
import { getAutomaticRelease, enableAutomaticRelease, stopAutomaticRelease } from './api.js'
vi.mock('./api.js', () => ({ getAutomaticRelease: vi.fn(), enableAutomaticRelease: vi.fn(), stopAutomaticRelease: vi.fn() }))
const preview = { available: true, run_id: 'execution-one', destination: { provider: 'sharepoint', folder_id: 'folder', folder_name: 'Reports' }, destination_label: 'SharePoint / Reports', authorization: null }
const authorized = { ...preview, authorization: { id: 'auth', status: 'active', expires_at: '2026-09-10T07:00:00+00:00', run_id: 'execution-one', files: ['a.docx'], destination_label: 'SharePoint / Reports', progress: { published: 0, pending: 1, failed: 0, blocked: 0 } } }
beforeEach(() => { getAutomaticRelease.mockResolvedValue(preview); enableAutomaticRelease.mockResolvedValue(authorized); stopAutomaticRelease.mockResolvedValue({}) })
afterEach(async () => { await unmountAll(); vi.resetAllMocks() })
async function mount(extra = {}) {
 const { root, container } = createTestRoot()
 const props = { scanId: 'scan', files: [{file:'a.docx'}], ...extra }
 const render = async changes => act(async()=>root.render(createElement(RemediationAutoRelease, {...props,...changes})))
 await render()
 return {container, render, checkbox:()=>container.querySelector('input'), button:name=>[...container.querySelectorAll('button')].find(b=>b.textContent.includes(name))}
}
const click = el => act(async()=>el.click())
it('is off by default, shows destination, and never authorizes on mount or scope change', async()=>{
 const v=await mount()
 expect(v.checkbox().checked).toBe(false)
 expect(v.container.textContent).toContain('SharePoint / Reports')
 await v.render({files:[{file:'b.docx'}]})
 expect(enableAutomaticRelease).not.toHaveBeenCalled()
 expect(stopAutomaticRelease).not.toHaveBeenCalled()
})
it('explicit checkbox authorizes only the displayed run, scope and destination', async()=>{
 const v=await mount()
 getAutomaticRelease.mockResolvedValue(authorized)
 await click(v.checkbox())
 expect(enableAutomaticRelease).toHaveBeenCalledOnce()
 expect(enableAutomaticRelease).toHaveBeenCalledWith('scan', expect.objectContaining({run_id:'execution-one',files:['a.docx'],destination:preview.destination,request_id:expect.any(String)}))
 expect(v.checkbox().checked).toBe(true)
 expect(v.container.textContent).toContain('release continues in the background')
 expect(v.container.textContent).toContain('Automatic release expires')
})
it('restores durable consent and stops future deliveries without changing approvals', async()=>{
 getAutomaticRelease.mockResolvedValue(authorized)
 const v=await mount()
 expect(v.checkbox().checked).toBe(true)
 expect(enableAutomaticRelease).not.toHaveBeenCalled()
 getAutomaticRelease.mockResolvedValue({...authorized,authorization:{...authorized.authorization,status:'stopped'}})
 await click(v.button('Stop future releases'))
 expect(stopAutomaticRelease).toHaveBeenCalledWith('scan','auth')
 expect(v.checkbox().checked).toBe(false)
 expect(v.container.textContent).toContain('Files already delivered remain available')
})
it.each([{readOnly:true}, {unavailable:true}])('disables unavailable or read-only authorization', async option=>{
 if(option.unavailable)getAutomaticRelease.mockResolvedValue({...preview,available:false,reason:'Start remediation first.'})
 const v=await mount(option)
 expect(v.checkbox().disabled).toBe(true)
 expect(enableAutomaticRelease).not.toHaveBeenCalled()
})
it('does not retry an unconfirmed authorization and offers status refresh', async()=>{
 enableAutomaticRelease.mockRejectedValue(new TypeError('Connection lost'))
 const v=await mount()
 await click(v.checkbox())
 expect(v.checkbox().disabled).toBe(true)
 expect(v.container.querySelector('[role=alert]').textContent).toContain('Connection lost')
 expect(enableAutomaticRelease).toHaveBeenCalledOnce()
 getAutomaticRelease.mockResolvedValue(authorized)
 await click(v.button('Refresh status'))
 expect(v.checkbox().checked).toBe(true)
 expect(enableAutomaticRelease).toHaveBeenCalledOnce()
})

it('keeps the original scope visible and never expands consent when file selection changes', async()=>{
 getAutomaticRelease.mockResolvedValue(authorized)
 const v=await mount()
 await v.render({files:[{file:'a.docx'},{file:'b.docx'}]})
 expect(v.container.textContent).toContain('Enabled for 1 file')
 expect(v.container.textContent).toContain('Changing the selection does not add files')
 expect(enableAutomaticRelease).not.toHaveBeenCalled()
 expect(v.button('Stop future releases')).toBeTruthy()
})
it('ignores a delayed read from a previous scan', async()=>{
 let resolveOld
 getAutomaticRelease.mockImplementationOnce(()=>new Promise(resolve=>{resolveOld=resolve}))
 const v=await mount()
 await v.render({scanId:'new-scan'})
 await act(async()=>resolveOld(authorized))
 expect(v.checkbox().checked).toBe(false)
 expect(enableAutomaticRelease).not.toHaveBeenCalled()
})

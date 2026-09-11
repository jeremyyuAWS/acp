import { act, createElement } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationAutoRelease from './RemediationAutoRelease.jsx'
import { getAutomaticRelease, enableAutomaticRelease, stopAutomaticRelease } from './api.js'
vi.mock('./api.js', () => ({ getAutomaticRelease: vi.fn(), enableAutomaticRelease: vi.fn(), stopAutomaticRelease: vi.fn(), resumeAutomaticRelease: vi.fn() }))
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
 expect(enableAutomaticRelease).toHaveBeenCalledWith('scan', expect.objectContaining({run_id:'execution-one',files:['a.docx'],destination:preview.destination,request_id:expect.any(String),allow_remaining_issues:true,include_reports:true}))
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

it('describes saved remaining-issue authorization without claiming reviews block release',async()=>{
 getAutomaticRelease.mockResolvedValue({...authorized,authorization:{...authorized.authorization,allow_remaining_issues:true,include_reports:true}})
 const v=await mount();expect(v.container.textContent).toContain('Human inspection is optional');expect(v.container.textContent).toContain('per-file checklist');expect(v.container.textContent).not.toContain('required approvals and verification pass')
})

it('shows stalled delivery reasons by file without presenting repeated checks as progress', async()=>{
 const reason='No delivery progress for 10 minutes. Check the destination and delivery receipt before retrying; a copy may already exist.'
 getAutomaticRelease.mockResolvedValue({...authorized,authorization:{...authorized.authorization,status:'blocked',needs_attention:true,attention_reason:reason,last_progress_at:'2026-09-10T06:00:00Z',files:['a.docx','b.docx'],progress:{published:0,pending:0,blocked:2,failed:0},file_progress:{
  'a.docx':{state:'publishing',message:'Checking delivery receipt. A copy may already exist.'},
  'b.docx':{state:'waiting',message:'Corrected copy is ready. Waiting for the current delivery to finish.'}
 }}})
 const v=await mount({files:[{file:'a.docx'},{file:'b.docx'}]})
 expect(v.container.querySelector('[role=status]').textContent).toContain(reason)
 expect(v.container.textContent).not.toContain('release continues in the background')
 expect(v.container.textContent).not.toContain('Waiting for this run to finish remediating')
 expect(v.container.querySelector('details').open).toBe(true)
 expect(v.container.querySelectorAll('li')).toHaveLength(2)
 expect(v.container.textContent).toContain('Checking delivery')
 expect(v.container.textContent).toContain('Corrected copy is ready')
 const attention=[...v.container.querySelectorAll('dt')].find(el=>el.textContent==='Needs attention')
 expect(attention.nextElementSibling.textContent).toBe('2')
 expect(v.checkbox().checked).toBe(true)
 expect(v.button('Stop future releases')).toBeTruthy()
 expect(enableAutomaticRelease).not.toHaveBeenCalled()
})

it('keeps an actively processing authorization enabled without a stall banner',async()=>{
 getAutomaticRelease.mockResolvedValue({...authorized,authorization:{...authorized.authorization,status:'processing',needs_attention:false,file_progress:{'a.docx':{state:'published',message:'Delivered'}}}})
 const v=await mount()
 expect(v.checkbox().checked).toBe(true)
 expect(v.container.querySelector('[role=status]')).toBeNull()
 expect(v.container.querySelector('details').open).toBe(false)
 expect(v.container.textContent).toContain('Delivered')
 expect(v.button('Stop future releases')).toBeTruthy()
})

it('does not claim an uncertain terminal delivery never reached the destination',async()=>{
 getAutomaticRelease.mockResolvedValue({...authorized,authorization:{...authorized.authorization,status:'failed'}})
 const v=await mount()
 expect(v.container.textContent).toContain('Delivery is not confirmed for files needing attention.')
 expect(v.container.textContent).not.toContain('Files needing attention have not been released.')
})

it('offers reconnect only when the saved release explicitly requires Drive access', async () => {
 getAutomaticRelease.mockResolvedValue({...authorized, authorization:{...authorized.authorization,status:'blocked',requires_reconnect:true}})
 const v = await mount()
 expect(v.button('Reconnect Google Drive')).toBeTruthy()
 expect(enableAutomaticRelease).not.toHaveBeenCalled()
 await v.render({readOnly:true})
 expect(v.button('Reconnect Google Drive').disabled).toBe(true)
})
it('never offers reconnect for stopped or expired authorization', async () => {
 getAutomaticRelease.mockResolvedValue({...authorized, authorization:{...authorized.authorization,status:'expired',requires_reconnect:true}})
 const v = await mount()
 expect(v.button('Reconnect Google Drive')).toBeUndefined()
})
it('reports server-confirmed execution identity for read-only absence of automatic publishing', async () => {
 const onStatus = vi.fn()
 const v = await mount({ statusOnly: true, onStatus })
 expect(v.container.textContent).toBe('')
 expect(onStatus.mock.calls.at(-1)[0]).toEqual({ scanId: 'scan', runId: 'execution-one', authorization: null })
 expect(enableAutomaticRelease).not.toHaveBeenCalled()
})
it('does not report confirmed absence when the initial status request fails', async () => {
 getAutomaticRelease.mockRejectedValue(new Error('unavailable'))
 const onStatus = vi.fn()
 await mount({ statusOnly: true, onStatus })
 expect(onStatus.mock.calls.at(-1)[0]).toEqual({ scanId: 'scan', runId: undefined, authorization: undefined })
})

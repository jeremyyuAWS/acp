import { act, createElement, StrictMode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import DriveReleaseReconnect from './DriveReleaseReconnect.jsx'
import { reconnectDriveForRelease } from './driveAuth.js'
import { noteAuthChange, _resetAuthEpoch } from './apiIdentity.js'
import { refreshSPToken } from './spAuth.js'
import { setDriveToken, setSPToken } from './api.js'
import { _resetRecoveryAttempts } from './useAutomaticDeliveryRecovery.js'
vi.mock('./driveAuth.js', () => ({ reconnectDriveForRelease: vi.fn() }))
vi.mock('./api.js', () => ({ setDriveToken: vi.fn(), setSPToken: vi.fn() }))
vi.mock('./spAuth.js', () => ({ refreshSPToken: vi.fn() }))
afterEach(async () => { await unmountAll(); vi.resetAllMocks(); sessionStorage.clear(); _resetAuthEpoch(); _resetRecoveryAttempts(); vi.useRealTimers() })
const authorization = { id:'saved',run_id:'run',revision:1,status:'blocked',can_resume:true,
  requires_reconnect:true,source_revision:'source',files:['file.docx'],destination:{provider:'drive',folder_id:'folder'} }
const banner = () => document.querySelector('.release-recovery-banner')
async function mount(extra = {}) {
 const {root, container} = createTestRoot()
 const props = {scanId:'scan',authorizationId:'saved',authorization,owner:'owner',onResume:vi.fn().mockResolvedValue({}),onRefresh:vi.fn(),...extra}
 await act(async () => root.render(createElement(DriveReleaseReconnect, props)))
 return {root,container,props,click:() => act(async () => banner()?.querySelector('button')?.click()),
  rerender:extra=>act(async()=>root.render(createElement(DriveReleaseReconnect,{...props,...extra})))}
}
it('keeps Google sign-in explicit and installs access before resuming the saved permission', async () => {
 reconnectDriveForRelease.mockResolvedValue('new-token')
 const v=await mount(); expect(reconnectDriveForRelease).not.toHaveBeenCalled()
 expect(banner().textContent).toContain('Google Drive sign-in is required')
 await v.click()
 expect(setDriveToken).toHaveBeenCalledWith('new-token')
 expect(v.props.onResume).toHaveBeenCalledOnce()
 expect(setDriveToken.mock.invocationCallOrder[0]).toBeLessThan(v.props.onResume.mock.invocationCallOrder[0])
 expect(banner().textContent).toContain('Checking saved delivery status')
 expect(banner().querySelector('button')).toBeNull()
})
it('recovers eligible saved delivery on mount without a click or unnecessary Google grant',async()=>{
 const v=await mount({requiresReconnect:false})
 expect(v.props.onResume).toHaveBeenCalledOnce()
 expect(reconnectDriveForRelease).not.toHaveBeenCalled()
 expect(banner().textContent).not.toContain('sign-in')
 expect(banner().querySelector('button')).toBeNull()
 await v.rerender({}); expect(v.props.onResume).toHaveBeenCalledOnce()
})
it('reload checks the durable status without repeating an already accepted POST',async()=>{
 const resume=vi.fn().mockResolvedValue({})
 await mount({requiresReconnect:false,onResume:resume}); await unmountAll(); _resetRecoveryAttempts()
 await mount({requiresReconnect:false,onResume:resume})
 expect(resume).toHaveBeenCalledOnce(); expect(banner().textContent).toContain('Checking saved delivery status')
})
it('unknown request outcome is not repeated on rerender or reload, but a new durable revision can retry',async()=>{
 const resume=vi.fn().mockRejectedValue(new Error('Connection lost'))
 const v=await mount({requiresReconnect:false,onResume:resume})
 expect(banner()).toBeNull()
 await v.rerender({}); await unmountAll(); _resetRecoveryAttempts()
 await mount({requiresReconnect:false,onResume:resume}); expect(resume).toHaveBeenCalledOnce()
 await unmountAll(); await mount({requiresReconnect:false,onResume:resume,authorization:{...authorization,revision:2}})
 expect(resume).toHaveBeenCalledTimes(2)
})
it('silently renews Microsoft access without persisting stale credentials or opening a popup',async()=>{
 refreshSPToken.mockResolvedValue('new-microsoft-token')
 const v=await mount({provider:'sharepoint'})
 expect(refreshSPToken).toHaveBeenCalledWith({interactive:false,persist:false})
 expect(setSPToken).toHaveBeenCalledWith('new-microsoft-token')
 expect(v.props.onResume).toHaveBeenCalledOnce()
 expect(sessionStorage.getItem('sp_token')).toBe('new-microsoft-token')
 expect(reconnectDriveForRelease).not.toHaveBeenCalled()
})
it('shows the amber sign-in action when silent Microsoft renewal requires interaction',async()=>{
 refreshSPToken.mockRejectedValueOnce(new Error('interaction_required')).mockResolvedValueOnce('interactive-token')
 const v=await mount({provider:'sharepoint'})
 expect(v.props.onResume).not.toHaveBeenCalled()
 expect(banner().classList.contains('release-recovery-banner--attention')).toBe(true)
 expect(banner().textContent).toContain('SharePoint sign-in is required')
 await v.click()
 expect(refreshSPToken).toHaveBeenLastCalledWith({interactive:true,persist:false})
 expect(v.props.onResume).toHaveBeenCalledOnce()
})
it('cancelled Google sign-in never resumes or installs credentials',async()=>{
 reconnectDriveForRelease.mockRejectedValue(new Error('Sign-in cancelled'))
 const v=await mount(); await v.click()
 expect(v.props.onResume).not.toHaveBeenCalled(); expect(setDriveToken).not.toHaveBeenCalled()
 expect(banner().textContent).toContain('Sign-in cancelled')
})
it.each(['scan','account','unmount'])('rejects late Microsoft grant after %s changes',async change=>{
 let finish; refreshSPToken.mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
 const v=await mount({provider:'sharepoint'})
 if(change==='scan') await v.rerender({scanId:'other',readOnly:true})
 if(change==='account') noteAuthChange('old','new')
 if(change==='unmount') await unmountAll()
 await act(async()=>finish('stale-token'))
 expect(setSPToken).not.toHaveBeenCalled(); expect(v.props.onResume).not.toHaveBeenCalled()
 expect(sessionStorage.getItem('sp_token')).toBeNull()
})
it('does not show or act on historical, manual, missing, expired, or stopped authorizations',async()=>{
 for(const extra of [{readOnly:true},{authorization:null},{owner:''},
  {authorization:{...authorization,status:'stopped'}},{authorization:{...authorization,expires_at:'2020-01-01'}},
  {authorization:{...authorization,can_resume:false,requires_reconnect:false}},{authorizationId:'other'}]) {
  await mount({requiresReconnect:false,...extra}); expect(banner()).toBeNull(); await unmountAll()
 }
 expect(reconnectDriveForRelease).not.toHaveBeenCalled(); expect(refreshSPToken).not.toHaveBeenCalled()
})
it('coalesces concurrent recovery mounts for the same saved permission',async()=>{
 let finish;const resume=vi.fn(()=>new Promise(resolve=>{finish=resolve}))
 await mount({requiresReconnect:false,onResume:resume}); await mount({requiresReconnect:false,onResume:resume})
 expect(resume).toHaveBeenCalledOnce(); await act(async()=>finish({}))
})
it('a timed out request remains uncertain and ignores late completion',async()=>{
 vi.useFakeTimers();let finish;const resume=vi.fn(()=>new Promise(resolve=>{finish=resolve}))
 const v=await mount({requiresReconnect:false,onResume:resume})
 await act(async()=>vi.advanceTimersByTime(20001))
 expect(banner()).toBeNull()
 const refreshes=v.props.onRefresh.mock.calls.length
 await act(async()=>finish({}))
 expect(v.props.onRefresh).toHaveBeenCalledTimes(refreshes)
 await v.rerender({});expect(resume).toHaveBeenCalledOnce()
})
it('positions the differently colored recovery banner below the ACP update header',async()=>{
 const header=document.createElement('div');const dismiss=document.createElement('button')
 dismiss.setAttribute('aria-label','Dismiss version notification');header.appendChild(dismiss)
 header.getBoundingClientRect=()=>({height:48});document.body.appendChild(header)
 await mount();expect(banner().style.top).toBe('48px');header.remove()
})

it('StrictMode effect replay still recovers once after silent renewal',async()=>{
 refreshSPToken.mockResolvedValue('microsoft-token')
 const {root}=createTestRoot();const resume=vi.fn().mockResolvedValue({})
 await act(async()=>root.render(createElement(StrictMode,null,createElement(DriveReleaseReconnect,{scanId:'scan',authorizationId:'saved',authorization,owner:'owner',provider:'sharepoint',onResume:resume}))))
 expect(refreshSPToken).toHaveBeenCalledOnce();expect(resume).toHaveBeenCalledOnce()
})
it('retires the unconfirmed banner after a provider request failure',async()=>{
 refreshSPToken.mockResolvedValue('microsoft-token')
 const resume=vi.fn().mockRejectedValue(new Error('Network interrupted'))
 await mount({provider:'sharepoint',onResume:resume})
 expect(banner()).toBeNull()
 expect(resume).toHaveBeenCalledOnce()
})

it('preserves the manual continuation explicit reconnect contract without automatic authority',async()=>{
 reconnectDriveForRelease.mockResolvedValue('explicit-grant')
 const v=await mount({authorization:null})
 expect(reconnectDriveForRelease).not.toHaveBeenCalled();expect(v.props.onResume).not.toHaveBeenCalled()
 expect(banner()).toBeNull()
 await act(async()=>v.container.querySelector('button').click())
 expect(setDriveToken).toHaveBeenCalledWith('explicit-grant');expect(v.props.onResume).toHaveBeenCalledOnce()
})

it('same-revision reload keeps the unconfirmed banner retired without another POST',async()=>{
 const resume=vi.fn().mockRejectedValue(new Error('Unknown request outcome'))
 await mount({requiresReconnect:false,onResume:resume});await unmountAll();_resetRecoveryAttempts()
 const v=await mount({requiresReconnect:false,onResume:resume})
 expect(banner()).toBeNull()
 expect(resume).toHaveBeenCalledOnce()
 await v.rerender({});expect(resume).toHaveBeenCalledOnce()
})
it('silent renewal timeout before POST does not pretend delivery is running or ask for unnecessary sign-in',async()=>{
 vi.useFakeTimers();refreshSPToken.mockImplementation(()=>new Promise(()=>{}))
 const v=await mount({provider:'sharepoint'})
 await act(async()=>vi.advanceTimersByTime(20001))
 expect(v.props.onResume).not.toHaveBeenCalled()
 expect(banner()).toBeNull()
 expect(refreshSPToken).toHaveBeenCalledOnce();expect(v.props.onResume).not.toHaveBeenCalled()
})

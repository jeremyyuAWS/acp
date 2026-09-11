import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import DriveReleaseReconnect from './DriveReleaseReconnect.jsx'
import { reconnectDriveForRelease } from './driveAuth.js'
import { noteAuthChange, _resetAuthEpoch } from './apiIdentity.js'
import { setDriveToken } from './api.js'
vi.mock('./driveAuth.js', () => ({ reconnectDriveForRelease: vi.fn() }))
vi.mock('./api.js', () => ({ setDriveToken: vi.fn() }))
afterEach(async () => { await unmountAll(); vi.resetAllMocks(); sessionStorage.clear(); _resetAuthEpoch() })
async function mount(extra = {}) {
 const {root, container} = createTestRoot()
 const props = {scanId:'scan',authorizationId:'saved',onResume:vi.fn().mockResolvedValue({}),...extra}
 await act(async () => root.render(createElement(DriveReleaseReconnect, props)))
 return {root,container,props,click:() => act(async () => container.querySelector('button').click())}
}
it('renews access before resuming only the saved authorization', async () => {
 reconnectDriveForRelease.mockResolvedValue('new-token')
 const v = await mount()
 expect(reconnectDriveForRelease).not.toHaveBeenCalled()
 await v.click()
 expect(setDriveToken).toHaveBeenCalledWith('new-token')
 expect(v.props.onResume).toHaveBeenCalledOnce()
 expect(setDriveToken.mock.invocationCallOrder[0]).toBeLessThan(v.props.onResume.mock.invocationCallOrder[0])
 expect(v.container.textContent).toContain('ACP is checking delivery')
 expect(v.container.querySelector('button').disabled).toBe(true)
})
it('does not resume after cancelled sign-in', async () => {
 reconnectDriveForRelease.mockRejectedValue(new Error('Sign-in cancelled'))
 const v = await mount(); await v.click()
 expect(v.props.onResume).not.toHaveBeenCalled()
 expect(setDriveToken).not.toHaveBeenCalled()
 expect(v.container.querySelector('[role=alert]').textContent).toContain('Sign-in cancelled')
})
it('ignores a grant returned after switching scans', async () => {
 let finish
 reconnectDriveForRelease.mockImplementation(() => new Promise(resolve => {finish=resolve}))
 const v=await mount(); await v.click()
 await act(async () => v.root.render(createElement(DriveReleaseReconnect, {...v.props,scanId:'other'})))
 await act(async () => finish('stale-token'))
 expect(v.props.onResume).not.toHaveBeenCalled()
 expect(setDriveToken).not.toHaveBeenCalled()
})
it('prevents historical releases from reconnecting', async () => {
 const v=await mount({readOnly:true}); await v.click()
 expect(reconnectDriveForRelease).not.toHaveBeenCalled()
})

it('resumes a recoverable delivery without asking for an unnecessary Google grant', async () => {
 const v=await mount({requiresReconnect:false}); await v.click()
 expect(reconnectDriveForRelease).not.toHaveBeenCalled()
 expect(v.props.onResume).toHaveBeenCalledOnce()
})

it('never installs a late grant after the ACP account changes', async () => {
 let finish
 reconnectDriveForRelease.mockImplementation(() => new Promise(resolve => {finish=resolve}))
 const v=await mount(); await v.click()
 noteAuthChange('old-account','new-account')
 await act(async () => finish('old-grant'))
 expect(setDriveToken).not.toHaveBeenCalled()
 expect(v.props.onResume).not.toHaveBeenCalled()
})

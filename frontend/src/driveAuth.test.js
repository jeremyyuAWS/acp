import { afterEach, expect, it, vi } from 'vitest'
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.resetModules(); vi.useRealTimers() })
async function setup() {
 vi.stubEnv('VITE_GOOGLE_CLIENT_ID', 'test-client')
 let config
 const requestAccessToken = vi.fn()
 const hasGrantedAllScopes = vi.fn().mockReturnValue(true)
 vi.stubGlobal('google', {accounts:{oauth2:{initTokenClient: vi.fn(value => {config=value;return {requestAccessToken}}),hasGrantedAllScopes}}})
 const mod = await import('./driveAuth.js')
 return {mod,requestAccessToken,config:()=>config,hasGrantedAllScopes}
}
it('explicit reconnect requests write access and returns a valid grant', async () => {
 const v=await setup(); const grant=v.mod.reconnectDriveForRelease()
 expect(v.config().scope).toContain('drive.file')
 expect(v.requestAccessToken).toHaveBeenCalledWith({prompt:'consent'})
 v.config().callback({access_token:'grant'})
 await expect(grant).resolves.toBe('grant')
})
it('rejects denied write scope and popup cancellation', async () => {
 const v=await setup(); v.hasGrantedAllScopes.mockReturnValue(false)
 const grant=v.mod.reconnectDriveForRelease(); v.config().callback({access_token:'readonly'})
 await expect(grant).rejects.toThrow('Allow Google Drive file access')
 const next=v.mod.reconnectDriveForRelease(); v.config().error_callback({type:'popup_closed'})
 await expect(next).rejects.toThrow('cancelled')
})
it('silent refresh preserves the write scope used by releases', async () => {
 const v=await setup(); const grant=v.mod.refreshDriveToken()
 expect(v.config().scope).toContain('drive.file')
 expect(v.requestAccessToken).toHaveBeenCalledWith({prompt:''})
 v.config().callback({access_token:'renewed'})
 await expect(grant).resolves.toBe('renewed')
})

it('fails closed on missing scope verification unless response confirms both scopes', async () => {
 const v=await setup()
 window.google.accounts.oauth2.hasGrantedAllScopes = undefined
 const denied=v.mod.reconnectDriveForRelease(); v.config().callback({access_token:'no-scope'})
 await expect(denied).rejects.toThrow('Allow Google Drive file access')
 const allowed=v.mod.reconnectDriveForRelease(); v.config().callback({access_token:'both',scope:'https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file'})
 await expect(allowed).resolves.toBe('both')
})

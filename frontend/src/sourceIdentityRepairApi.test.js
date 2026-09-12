import { afterEach, expect, it, vi } from 'vitest'
const refresh=vi.hoisted(()=>vi.fn())
vi.mock('./spAuth.js',()=>({refreshSPToken:refresh}))
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();vi.resetModules();refresh.mockReset()})
async function setup() {
 vi.stubEnv('VITE_SIM','false');vi.resetModules()
 const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>({status:'repaired',repaired_files:147})})
 vi.stubGlobal('fetch',fetch)
 const api=await import('./api.js');api.setMsToken('account-bearer');api.setSPToken('old-source-token')
 return {api,fetch}
}
it('silently refreshes Microsoft credentials and sends one metadata-only POST without consent',async()=>{
 const {api,fetch}=await setup();refresh.mockResolvedValue('fresh-source-token')
 const signal=new AbortController().signal
 await api.repairAutomaticReleaseSourceIdentity('scan/id',{signal})
 expect(refresh).toHaveBeenCalledWith({interactive:false})
 expect(fetch).toHaveBeenCalledTimes(1)
 expect(fetch.mock.calls[0][0]).toContain('/scans/scan%2Fid/release/automatic/repair-source-identity')
 expect(fetch.mock.calls[0][1]).toEqual({method:'POST',signal,headers:expect.objectContaining({'Authorization':'Bearer account-bearer','X-Auth-Provider':'microsoft','X-SP-Token':'fresh-source-token'})})
 expect(fetch.mock.calls[0][1].body).toBeUndefined()
})
it('does not post stale credentials after a silent refresh fails',async()=>{
 const {api,fetch}=await setup();refresh.mockRejectedValue(new Error('Interaction required'))
 await expect(api.repairAutomaticReleaseSourceIdentity('scan')).rejects.toThrow('Interaction required')
 expect(fetch).not.toHaveBeenCalled()
})
it('does not post if the account changes or scope is aborted during credential refresh',async()=>{
 const {api,fetch}=await setup();refresh.mockImplementation(async()=>{api.setMsToken('other-account');return 'fresh'})
 await expect(api.repairAutomaticReleaseSourceIdentity('scan')).rejects.toThrow('account changed')
 expect(fetch).not.toHaveBeenCalled()
 const controller=new AbortController();refresh.mockImplementation(async()=>{controller.abort();return 'fresh'})
 await expect(api.repairAutomaticReleaseSourceIdentity('scan',{signal:controller.signal})).rejects.toMatchObject({name:'AbortError'})
 expect(fetch).not.toHaveBeenCalled()
})
it('never retries an uncertain metadata POST',async()=>{
 const {api,fetch}=await setup();refresh.mockResolvedValue('fresh');fetch.mockRejectedValue(new TypeError('Connection lost'))
 await expect(api.repairAutomaticReleaseSourceIdentity('scan')).rejects.toThrow('Connection lost')
 expect(fetch).toHaveBeenCalledTimes(1)
})

it('marks credential failures as pre-dispatch so reconnection can safely resume recovery',async()=>{
 const {api,fetch}=await setup();refresh.mockRejectedValue(new Error('Interaction required'))
 await expect(api.repairAutomaticReleaseSourceIdentity('scan')).rejects.toMatchObject({code:'microsoft_connection_required',sourceIdentityRequestSent:false})
 expect(fetch).not.toHaveBeenCalled()
})

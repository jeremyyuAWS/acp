import { afterEach, expect, it, vi } from 'vitest'
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();vi.resetModules()})
it('reads the uncached recorded queue with the bounded refresh abort signal',async()=>{
 vi.stubEnv('VITE_SIM','false');vi.resetModules()
 const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>[{id:'recorded',status:'pending'}]})
 vi.stubGlobal('fetch',fetch)
 const api=await import('./api.js')
 const signal=new AbortController().signal
 expect(await api.listHitlQueue('scan/id',null,{signal})).toEqual([{id:'recorded',status:'pending'}])
 expect(fetch.mock.calls[0][0]).toContain('/hitl/queue?scan_id=scan%2Fid')
 expect(fetch.mock.calls[0][1]).toEqual({headers:expect.any(Object),cache:'no-store',signal})
})

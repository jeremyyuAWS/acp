import { afterEach, expect, it, vi } from 'vitest'
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();vi.resetModules()})
it('keeps preview read-only and sends exact explicit consent and stop requests', async()=>{
 vi.stubEnv('VITE_SIM','false');vi.resetModules()
 const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>({available:true})})
 vi.stubGlobal('fetch',fetch)
 const {getAutomaticRelease,enableAutomaticRelease,stopAutomaticRelease}=await import('./api.js')
 const signal=new AbortController().signal
 await getAutomaticRelease('scan/id',['a & b.docx','two.pptx'],{signal})
 const url=new URL(fetch.mock.calls[0][0])
 expect(url.pathname).toBe('/scans/scan%2Fid/release/automatic')
 expect(url.searchParams.getAll('files')).toEqual(['a & b.docx','two.pptx'])
 expect(fetch.mock.calls[0][1]).toMatchObject({signal})
 expect(fetch.mock.calls[0][1].method).toBeUndefined()
 const intent={run_id:'execution',files:['a & b.docx'],destination:{provider:'sharepoint',folder_id:'folder'},request_id:'exact-request'}
 await enableAutomaticRelease('scan/id',intent)
 expect(fetch.mock.calls[1][1].method).toBe('POST')
 expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual(intent)
 await stopAutomaticRelease('scan/id','auth/id')
 expect(fetch.mock.calls[2][0]).toContain('/automatic/auth%2Fid/stop')
 expect(fetch.mock.calls[2][1].method).toBe('POST')
})

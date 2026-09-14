import { afterEach, expect, it, vi } from 'vitest'
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();vi.resetModules()})
it('preserves legacy empty fallback but exposes failures for the drawer',async()=>{
 vi.stubEnv('VITE_SIM','false');vi.resetModules()
 vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('offline')))
 const {getFileRemediationDiffs}=await import('./api.js')
 await expect(getFileRemediationDiffs('scan','sample.docx')).resolves.toEqual([])
 await expect(getFileRemediationDiffs('scan','sample.docx',{strict:true})).rejects.toThrow('offline')
})
it('keeps a successful empty evidence response distinct from a transport failure',async()=>{
 vi.stubEnv('VITE_SIM','false');vi.resetModules()
 const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>[]})
 vi.stubGlobal('fetch',fetch)
 const {getFileRemediationDiffs}=await import('./api.js')
 await expect(getFileRemediationDiffs('scan/id','sample file.docx',{strict:true})).resolves.toEqual([])
 expect(fetch.mock.calls[0][0]).toContain('/scans/scan%2Fid/files/sample%20file.docx/remediation-diffs')
 expect(fetch.mock.calls[0][1].method).toBeUndefined()
})

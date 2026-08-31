import {it,expect,vi,afterEach} from 'vitest'
vi.mock('./sim.js', async original => ({...(await original()),SIM:false}))
const {checkDiscoveryPreflight} = await import('./api.js')
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();vi.useRealTimers()})
it('aborts a stalled advisory preflight while preserving folder scope', async()=>{
 vi.useFakeTimers()
 const controller=new AbortController()
 vi.spyOn(AbortSignal,'timeout').mockImplementation(ms=>{
   setTimeout(()=>controller.abort(),ms); return controller.signal
 })
 const fetcher=vi.fn((url,opts)=>new Promise((resolve,reject)=>{
   opts.signal.addEventListener('abort',()=>reject(new Error('preflight timeout')))
 }))
 vi.stubGlobal('fetch',fetcher)
 const result=expect(checkDiscoveryPreflight('drive',null,[{id:'selected'}])).rejects.toThrow('preflight timeout')
 await vi.advanceTimersByTimeAsync(8000)
 await result
 expect(fetcher.mock.calls[0][0]).toContain('folders=selected')
})

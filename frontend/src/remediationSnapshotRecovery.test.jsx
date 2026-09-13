import React, { act } from 'react'
import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
const snapshot=vi.fn(), stream=vi.fn(), close=vi.fn()
vi.mock('./api.js',()=>({getRemediationSnapshot:(...a)=>snapshot(...a),openRemediationStream:(...a)=>stream(...a),getRecentRemediationActivity:vi.fn(async()=>({available:true,events:[]}))}))
const {useRemediationRun}=await import('./useRemediationRun.js')
globalThis.IS_REACT_ACT_ENVIRONMENT = true
let state
function Harness(){state=useRemediationRun('scan');return null}
async function mount(){const{root}=createTestRoot();await act(async()=>root.render(<Harness/>))}
beforeEach(()=>{vi.useFakeTimers();snapshot.mockReset();stream.mockReset().mockReturnValue({close});close.mockReset()})
afterEach(async()=>{await unmountAll();vi.useRealTimers()})
it('recovers a missing initial snapshot even when status frames continue without snapshots',async()=>{
 snapshot.mockRejectedValueOnce(Object.assign(new Error('temporarily unavailable'),{status:503})).mockResolvedValue({scan_id:'scan',revision:1,terminal:false})
 await mount();await act(async()=>stream.mock.calls[0][1].onMessage({running:1}))
 await act(async()=>vi.advanceTimersByTimeAsync(5000))
 expect(snapshot).toHaveBeenCalledTimes(2);expect(state.snapshot?.revision).toBe(1)
})
it('never overlaps slow snapshot reads on fallback polling',async()=>{
 let resolve;snapshot.mockImplementation(()=>new Promise(r=>{resolve=r}))
 await mount();await act(async()=>stream.mock.calls[0][1].onError())
 await act(async()=>vi.advanceTimersByTimeAsync(15000))
 expect(snapshot).toHaveBeenCalledTimes(1)
 await act(async()=>resolve({scan_id:'scan',revision:1,terminal:false}))
})
it.each([401,403,404])('stops repeat requests after terminal owner/session denial %s',async status=>{
 snapshot.mockRejectedValue(Object.assign(new Error('not accessible'),{status}))
 await mount();await act(async()=>vi.advanceTimersByTimeAsync(20000))
 expect(snapshot).toHaveBeenCalledTimes(1);expect(state.snapshot).toBe(null);expect(state.connected).toBe(false)
 expect(close).toHaveBeenCalledTimes(1)
})
it('retains confirmed totals during transient snapshot failures and rejects stale stream totals',async()=>{
 const confirmed={scan_id:'scan',revision:3,terminal:false,documents:{completed:5}}
 snapshot.mockResolvedValueOnce(confirmed).mockRejectedValue(Object.assign(new Error('network'),{status:503}))
 await mount()
 const handlers=stream.mock.calls[0][1]
 await act(async()=>handlers.onMessage({snapshot:confirmed,running:2}))
 await act(async()=>handlers.onError())
 await act(async()=>vi.advanceTimersByTimeAsync(5000))
 expect(state.snapshot).toEqual(confirmed)
 await act(async()=>handlers.onMessage({snapshot:{...confirmed,revision:2,documents:{completed:1}},running:8}))
 expect(state.snapshot).toEqual(confirmed)
 expect(state.status.running).toBe(2)
})
it('refreshes a previously terminal snapshot when a new legacy work frame arrives',async()=>{
 snapshot.mockResolvedValueOnce({scan_id:'scan',revision:1,terminal:true}).mockResolvedValue({scan_id:'scan',revision:2,terminal:false})
 await mount();await act(async()=>stream.mock.calls[0][1].onMessage({running:1}))
 await act(async()=>vi.advanceTimersByTimeAsync(5000))
 expect(snapshot).toHaveBeenCalledTimes(2)
 expect(state.snapshot.terminal).toBe(false)
})
it('stops fallback polling after a stream supplies a reconciled snapshot and resumes after closing',async()=>{
 const confirmed={scan_id:'scan',revision:1,terminal:false}
 snapshot.mockResolvedValue(confirmed)
 await mount()
 const handlers=stream.mock.calls[0][1]
 await act(async()=>handlers.onMessage({running:1}))
 await act(async()=>vi.advanceTimersByTimeAsync(5000))
 expect(snapshot).toHaveBeenCalledTimes(2)
 await act(async()=>handlers.onMessage({running:1,snapshot:{...confirmed,revision:2}}))
 await act(async()=>vi.advanceTimersByTimeAsync(15000))
 expect(snapshot).toHaveBeenCalledTimes(2)
 await act(async()=>handlers.onDone())
 await act(async()=>vi.advanceTimersByTimeAsync(5000))
 expect(snapshot).toHaveBeenCalledTimes(3)
})

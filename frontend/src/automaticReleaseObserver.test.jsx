import { createElement, act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
vi.mock('./api.js',()=>({getAutomaticRelease:vi.fn()}))
import useStatus from './useAutomaticReleaseStatus.js'
import { noteAuthChange } from './apiIdentity.js'
function Host(props) { useStatus(props.scan,props.files,props.onStatus,props.get); return null }
afterEach(async()=>{await unmountAll();vi.useRealTimers()})
it('keeps durable publication status observed without mounting a publication action',async()=>{
 vi.useFakeTimers(); const get=vi.fn().mockResolvedValue({run_id:'batch',authorization:{id:'accepted',status:'processing'}}),onStatus=vi.fn()
 const {root}=createTestRoot()
 await act(async()=>root.render(createElement(Host,{scan:'scan',files:[{file:'a.docx'}],get,onStatus})))
 expect(onStatus).toHaveBeenLastCalledWith({scanId:'scan',runId:'batch',authorization:{id:'accepted',status:'processing'},pending:false,error:''})
 await act(async()=>vi.advanceTimersByTimeAsync(5000))
 expect(get).toHaveBeenCalledTimes(2)
 expect(get.mock.calls[0][1]).toEqual(['a.docx'])
})
it('does not deliver a stale response after scan navigation or account change',async()=>{
 let resolve;const get=vi.fn().mockImplementation(()=>new Promise(r=>{resolve=r})),onStatus=vi.fn()
 const {root}=createTestRoot()
 await act(async()=>root.render(createElement(Host,{scan:'old',files:[],get,onStatus})))
 const old=resolve
 await act(async()=>root.render(createElement(Host,{scan:'new',files:[],get,onStatus})))
 await act(async()=>old({run_id:'old-batch'}))
 expect(onStatus).not.toHaveBeenCalledWith(expect.objectContaining({runId:'old-batch'}))
 noteAuthChange('old-account','new-account')
 await act(async()=>resolve({run_id:'wrong-account'}))
 expect(onStatus).not.toHaveBeenCalledWith(expect.objectContaining({runId:'wrong-account'}))
})
it('stops polling on an ownership rejection',async()=>{
 vi.useFakeTimers();const get=vi.fn().mockRejectedValue(Object.assign(new Error('Forbidden'),{status:403})),onStatus=vi.fn()
 const {root}=createTestRoot();await act(async()=>root.render(createElement(Host,{scan:'scan',files:[],get,onStatus})))
 await act(async()=>vi.advanceTimersByTimeAsync(30000))
 expect(get).toHaveBeenCalledTimes(1)
})

it('reports a timed-out observer and retries with a new request instead of leaving Checking forever',async()=>{
 vi.useFakeTimers();const onStatus=vi.fn()
 const get=vi.fn().mockImplementationOnce(()=>new Promise(()=>{})).mockResolvedValue({run_id:'batch',authorization:null})
 const {root}=createTestRoot();await act(async()=>root.render(createElement(Host,{scan:'scan',files:[],get,onStatus})))
 await act(async()=>vi.advanceTimersByTimeAsync(20000))
 expect(onStatus).toHaveBeenLastCalledWith(expect.objectContaining({pending:false,error:expect.any(String)}))
 expect(get.mock.calls[0][2].signal.aborted).toBe(true)
 await act(async()=>vi.advanceTimersByTimeAsync(5000))
 expect(get).toHaveBeenCalledTimes(2)
 expect(get.mock.calls[1][2].signal.aborted).toBe(false)
 expect(onStatus).toHaveBeenLastCalledWith(expect.objectContaining({runId:'batch',pending:false,error:''}))
})

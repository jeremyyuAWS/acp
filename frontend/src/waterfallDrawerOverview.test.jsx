import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import WaterfallDrawerOverview, { selectedDrawerScope } from './WaterfallDrawerOverview.jsx'
import { getWaterfallDrawerMetrics } from './waterfallDrawerMetricsClient.js'
vi.mock('./waterfallDrawerMetricsClient.js', () => ({ drawerMetricScope: (scope = {}) => ({ stage:null, provider:null, model:null, ...scope }), getWaterfallDrawerMetrics: vi.fn() }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const payload = n => ({ contract_version:'waterfall-drawer-metrics.v1', revision:`hash-${n}`, contribution:{rows:[{id:'usable',label:'Validated usable',value:n}],unit:'attempts'}, pace:{value:1,observedSeconds:60},trend:{points:[]},spend:{rows:[]} })
const props = {scanId:'s',batchId:'r',identity:'owner:s:r',selectedModel:{stepId:'primary',provider:'p',model:'m'},role:'first',snapshot:{},live:true,selectTab:vi.fn()}
afterEach(async () => { await unmountAll(); vi.useRealTimers(); vi.clearAllMocks(); vi.unstubAllGlobals() })
it('does not infer a primary or fallback position from historical purpose', () => {
 expect(selectedDrawerScope({purpose:'fallback',model:'m',attemptIds:['a']})).toBeNull()
 expect(selectedDrawerScope({stepId:'fallback_2',model:'m',provider:'p'})).toEqual({stage:'fallback_2',model:'m',provider:'p'})
})
it('starts without a pulse, animates a live delta, and suppresses recovery history', async () => {
 vi.useFakeTimers(); getWaterfallDrawerMetrics.mockResolvedValueOnce(payload(1)).mockResolvedValueOnce(payload(3)).mockRejectedValueOnce(new Error('offline')).mockResolvedValue(payload(8))
 const {root,container}=createTestRoot()
 await act(async () => root.render(<WaterfallDrawerOverview {...props}/>))
 expect(container.querySelector('.wf-delta')).toBeNull()
 await act(async () => vi.advanceTimersByTimeAsync(15000))
 expect(container.querySelector('.wf-delta').textContent).toBe('+2')
 await act(async () => vi.advanceTimersByTimeAsync(15000))
 expect(container.textContent).toContain('Refresh delayed')
 await act(async () => vi.advanceTimersByTimeAsync(15000))
 expect(container.querySelector('.wf-delta')).toBeNull()
})
it('aborts old scope, ignores its late response, and stops polling on unmount', async () => {
 vi.useFakeTimers(); let resolveOld
 getWaterfallDrawerMetrics.mockImplementationOnce(() => new Promise(resolve => {resolveOld=resolve})).mockResolvedValue(payload(9))
 const {root,container}=createTestRoot()
 await act(async () => root.render(<WaterfallDrawerOverview {...props}/>))
 const signal=getWaterfallDrawerMetrics.mock.calls[0][3]
 await act(async () => root.render(<WaterfallDrawerOverview {...props} selectedModel={{stepId:'fallback_2',model:'m',provider:'p'}}/>))
 expect(signal.aborted).toBe(true)
 await act(async () => resolveOld(payload(70)))
 expect(container.querySelector('dd').textContent).toBe('9')
 await act(async () => root.render(null))
 const reads=getWaterfallDrawerMetrics.mock.calls.length
 await act(async () => vi.advanceTimersByTimeAsync(45000))
 expect(getWaterfallDrawerMetrics).toHaveBeenCalledTimes(reads)
})
it('clears denied data and does not poll completed runs', async () => {
 vi.useFakeTimers(); getWaterfallDrawerMetrics.mockResolvedValueOnce(payload(2)).mockRejectedValue(Object.assign(new Error('denied'),{status:403}))
 const {root,container}=createTestRoot()
 await act(async () => root.render(<WaterfallDrawerOverview {...props}/>))
 await act(async () => vi.advanceTimersByTimeAsync(15000))
 expect(container.querySelector('dd')).toBeNull()
 await act(async () => vi.advanceTimersByTimeAsync(30000))
 expect(getWaterfallDrawerMetrics).toHaveBeenCalledTimes(2)
 getWaterfallDrawerMetrics.mockResolvedValue(payload(4))
 await act(async () => root.render(<WaterfallDrawerOverview {...props} live={false}/>))
 const reads=getWaterfallDrawerMetrics.mock.calls.length
 await act(async () => vi.advanceTimersByTimeAsync(30000))
 expect(getWaterfallDrawerMetrics).toHaveBeenCalledTimes(reads)
})

it('explains disabled AI without loading charts or implying the stage is running', async () => {
 const {root,container}=createTestRoot()
 await act(async()=>root.render(<WaterfallDrawerOverview {...props} aiEnabled={false} snapshot={{fixes:{verified:175},review:{items:68}}}/>))
 expect(container.textContent).toContain('AI wasn’t enabled for this run')
 expect(container.textContent).not.toContain('Chart scope unavailable')
 expect(container.textContent).toContain('Overall run · in progress')
 expect(container.textContent).toContain('175')
 expect(container.textContent).toContain('68')
 expect(getWaterfallDrawerMetrics).not.toHaveBeenCalled()
 await act(async()=>container.querySelector('button').click())
 expect(props.selectTab).toHaveBeenCalledWith('Evidence')
})
it('does not replace rules with the disabled AI state', async()=>{
 const {root,container}=createTestRoot()
 await act(async()=>root.render(<WaterfallDrawerOverview {...props} aiEnabled={false} role="rules" selectedModel={null}/>))
 expect(container.textContent).not.toContain('AI wasn’t enabled')
 expect(container.textContent).toContain('Verified changes')
})

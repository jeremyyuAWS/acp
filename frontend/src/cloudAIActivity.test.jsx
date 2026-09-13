import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import CloudAIActivity, { AIActivityCharts, observedPaceScale } from './CloudAIActivity.jsx'
vi.mock('./useWaterfallDrawerMetrics.js', () => ({ default: vi.fn(() => ({})) }))
import useMetrics from './useWaterfallDrawerMetrics.js'
afterEach(async () => { await unmountAll(); vi.clearAllMocks() })
it('uses an explicit observed scale rather than inventing a performance target', () => {
 expect(observedPaceScale({value:3},{points:[{value:2},{value:8},{value:null}]}).scaleMax).toBe(8)
 expect(observedPaceScale({value:3},{points:[]}).scaleMax).toBeUndefined()
})
it('shows individual provider usage, charts and honest missing values', async () => {
 const {root,container}=createTestRoot()
 await act(async () => root.render(<AIActivityCharts data={{models:{rows:[{id:'anthropic:sonnet',label:'anthropic · sonnet',value:2,active:1,input_tokens:null,output_tokens:50,average_seconds:40,timed_attempts:1}]},pace:{value:2,observedSeconds:90,unit:'attempts/min'},trend:{points:[{timestamp:'2026-09-13T12:00:00Z',value:2}]},spend:{rows:[]},contribution:{rows:[]}}}/>))
 expect(container.textContent).toContain('anthropic · sonnet')
 expect(container.textContent).toContain('Unavailable')
 expect(container.querySelector('.wd-gauge')).not.toBeNull()
 expect(container.querySelector('.wd-trend')).not.toBeNull()
 expect(container.querySelector('[role="region"]').tabIndex).toBe(0)
 expect(container.textContent).toContain('not a verified repair')
})
it('preserves disabled AI and scopes usage to the exact current run', async () => {
 const {root,container}=createTestRoot()
 await act(async () => root.render(<CloudAIActivity scanId="s" batchId="r" aiEnabled={false} live/>))
 expect(container.textContent).toBe('')
 expect(useMetrics).toHaveBeenLastCalledWith(expect.objectContaining({scanId:'s',batchId:'r',enabled:false}))
})

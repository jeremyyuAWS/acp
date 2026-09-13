import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import { RemediationActivityPanel } from './RemediationOpsPanel.jsx'
afterEach(async()=>{await unmountAll();vi.useRealTimers()})
it('ages a retained successful snapshot independently when polling stops, and resets only for a confirmed reception',async()=>{
 vi.useFakeTimers();vi.setSystemTime(new Date('2026-09-13T21:00:00Z'))
 const {root,container}=createTestRoot()
 const snapshot={batch_id:'batch',scan_id:'scan',state:'running',terminal:false}
 const receivedAt=Date.now()-2000
 await act(async()=>root.render(<RemediationActivityPanel snapshot={snapshot} receivedAt={receivedAt} connected={false} updateMode="polling" />))
 expect(container.textContent).toContain('last update 2s ago')
 await act(async()=>vi.advanceTimersByTime(5000))
 expect(container.textContent).toContain('last update 7s ago')
 await act(async()=>root.render(<RemediationActivityPanel snapshot={snapshot} receivedAt={Date.now()} connected={false} updateMode="polling" />))
 expect(container.textContent).toContain('last update 0s ago')
 expect(container.textContent).not.toContain('Live updates')
})
it('handles an initially empty panel without conditional hooks and clears its ticking clock on unmount',async()=>{
 vi.useFakeTimers()
 const {root}=createTestRoot()
 await act(async()=>root.render(<RemediationActivityPanel snapshot={null} />))
 await act(async()=>root.render(<RemediationActivityPanel snapshot={{batch_id:'b',state:'running'}} receivedAt={Date.now()} />))
 expect(vi.getTimerCount()).toBeGreaterThan(0)
 await unmountAll()
 expect(vi.getTimerCount()).toBe(0)
})

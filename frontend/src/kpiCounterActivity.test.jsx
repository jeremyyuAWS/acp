import { act, createElement } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import Counter from './BidirectionalKpiCounter.jsx'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container, root, frames, nextFrame
beforeEach(() => {
 vi.useFakeTimers(); frames=new Map(); nextFrame=0
 vi.stubGlobal('requestAnimationFrame',vi.fn(callback=>{frames.set(++nextFrame,callback);return nextFrame}))
 vi.stubGlobal('cancelAnimationFrame',vi.fn(id=>frames.delete(id)))
 vi.stubGlobal('matchMedia',vi.fn(()=>({matches:false})))
 ;({container,root}=createTestRoot())
})
afterEach(async()=>{await unmountAll();vi.useRealTimers();vi.unstubAllGlobals()})
const render=async props=>act(async()=>root.render(createElement(Counter,props)))
const frame=async now=>act(async()=>{const callbacks=[...frames.values()];frames.clear();callbacks.forEach(cb=>cb(now))})
const count=()=>container.querySelector('.kpi-counter-value')
const delta=()=>container.querySelector('.kpi-update-delta')
it('does not claim activity on mount or unchanged ticks',async()=>{
 await render({value:147});await render({value:147})
 expect(count().textContent).toBe('147');expect(delta()).toBeNull();expect(requestAnimationFrame).not.toHaveBeenCalled()
})
it('animates draining queues down with a green minus delta and count highlight',async()=>{
 await render({value:147,positiveDirection:'decrease'});await render({value:137,positiveDirection:'decrease'})
 expect(count().classList.contains('kpi-counter-value--activity')).toBe(true)
 expect(delta().textContent).toBe('−10');expect(delta().classList.contains('kpi-update-delta--positive')).toBe(true)
 expect(delta().classList.contains('kpi-update-delta--decrease')).toBe(true)
 await frame(1000);await frame(1200);expect(count().textContent).toBe('142')
 await frame(1400);expect(count().textContent).toBe('137')
})
it('animates completed work up with a green plus delta',async()=>{
 await render({value:1,positiveDirection:'increase'});await render({value:5,positiveDirection:'increase'})
 expect(delta().textContent).toBe('+4');expect(delta().classList.contains('kpi-update-delta--positive')).toBe(true)
 expect(delta().classList.contains('kpi-update-delta--increase')).toBe(true)
 await frame(1000);await frame(1400);expect(count().textContent).toBe('5')
})
it('does not portray increasing attention as success',async()=>{
 await render({value:2,positiveDirection:'decrease'});await render({value:8,positiveDirection:'decrease'})
 expect(delta().textContent).toBe('+6');expect(delta().classList.contains('kpi-update-delta--warning')).toBe(true)
 expect(delta().classList.contains('kpi-update-delta--positive')).toBe(false)
})
it('keeps counters without a successful direction neutral',async()=>{
 await render({value:0});await render({value:10});expect(delta().classList.contains('kpi-update-delta--neutral')).toBe(true)
})
it('restarts highlight for rapid updates without confusing target delta with intermediate count',async()=>{
 await render({value:10,positiveDirection:'increase'});await render({value:20,positiveDirection:'increase'})
 await frame(1000);await frame(1200);expect(count().textContent).toBe('15')
 const oldNumber=count(),oldDelta=delta()
 await act(async()=>vi.advanceTimersByTime(1500));await render({value:25,positiveDirection:'increase'})
 expect(count()).not.toBe(oldNumber);expect(delta()).not.toBe(oldDelta);expect(delta().textContent).toBe('+5')
 await frame(2000);await frame(2400);expect(count().textContent).toBe('25')
 await act(async()=>vi.advanceTimersByTime(1000));expect(delta().textContent).toBe('+5')
 await act(async()=>vi.advanceTimersByTime(1001));expect(delta()).toBeNull()
 expect(count().classList.contains('kpi-counter-value--activity')).toBe(false)
})
it('respects reduced motion while preserving the signed update',async()=>{
 matchMedia.mockReturnValue({matches:true})
 await render({value:10,positiveDirection:'decrease'});await render({value:0,positiveDirection:'decrease'})
 expect(count().textContent).toBe('0');expect(delta().textContent).toBe('−10');expect(requestAnimationFrame).not.toHaveBeenCalled()
})
it('does not invent activity when an unknown baseline becomes known',async()=>{
 await render({value:null});expect(count().textContent).toBe('—')
 await render({value:9});expect(count().textContent).toBe('9');expect(delta()).toBeNull();expect(requestAnimationFrame).not.toHaveBeenCalled()
})
it('clears animation and pending frames when live animation is disabled',async()=>{
 await render({value:10});await render({value:5});expect(delta()).not.toBeNull()
 await render({value:3,animate:false});expect(count().textContent).toBe('3');expect(delta()).toBeNull();expect(frames.size).toBe(0)
})

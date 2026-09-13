import { act, createElement } from 'react'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import Summary from './RemediationProgressSummary.jsx'
let root, container
beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1)); vi.stubGlobal('cancelAnimationFrame', vi.fn()); vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false }))); ({ root, container } = createTestRoot()) })
afterEach(async () => { await unmountAll(); vi.useRealTimers(); vi.unstubAllGlobals() })
const render = async (states, key = 'scan-a') => act(async () => root.render(createElement(Summary, {key, variant:'release', animate:true, queueMode:true, onSelect:vi.fn(), documents:states.map((progressState, i) => ({file:`file-${i}`, progressState}))})))
it('starts from confirmed counts then flashes and drains only on a real update', async () => {
 await render(['processing','ready'])
 expect(container.querySelectorAll('.kpi-update-delta')).toHaveLength(0)
 expect(container.querySelectorAll('[aria-haspopup="dialog"]')).toHaveLength(5)
 await render(['published','ready'])
 expect(container.querySelector('.progress-processing .kpi-update-delta').textContent).toBe('−1')
 expect(container.querySelector('.progress-published .kpi-update-delta').textContent).toBe('+1')
 expect(container.querySelector('.progress-published .kpi-counter-value--activity')).not.toBeNull()
 await act(async () => vi.advanceTimersByTime(2000))
 await render(['published','ready'])
 expect(container.querySelectorAll('.kpi-update-delta')).toHaveLength(0)
 await render(['published','published'], 'scan-b')
 expect(container.querySelectorAll('.kpi-update-delta')).toHaveLength(0)
})
it('keeps the signed update readable without moving numbers under reduced motion', async () => {
 matchMedia.mockReturnValue({matches:true})
 await render(['ready']); await render(['published'])
 expect(container.querySelector('.progress-published .kpi-counter-value').textContent).toBe('1')
 expect(container.querySelector('.progress-published .kpi-update-delta').textContent).toBe('+1')
 expect(requestAnimationFrame).not.toHaveBeenCalled()
})

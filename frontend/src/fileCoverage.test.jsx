import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import FileCoverage from './FileCoverage.jsx'
import BidirectionalKpiCounter from './BidirectionalKpiCounter.jsx'
import { fileCoverage } from './fileCoverageModel.js'
let root, container
afterEach(async () => { if (root) await act(async () => root.unmount()); container?.remove(); vi.useRealTimers() })
async function mount(content) { container = document.createElement('div'); document.body.append(container); root = createRoot(container); await act(async () => root.render(content)) }
it('counts unique files with finished attempts, including unresolved failures, without counting retries or unstarted skipped work', () => {
  const files = ['a','a','b','c','d'].map(file => ({file,hasFindings:true}))
  const attempts = [{file:'a',state:'completed',attempted:true}, {file:'b',state:'failed',attempted:true},
    {file:'c',state:'failed',attempted:true},{file:'c',state:'queued',retryScheduled:true}, {file:'d',state:'skipped',attempted:false}]
  expect(fileCoverage({files,attempts})).toMatchObject({withFindings:4,processed:null,remaining:null,unknown:1})
  attempts[4] = {file:'d',state:'queued',attempted:false}
  expect(fileCoverage({files,attempts})).toMatchObject({withFindings:4,processed:2,remaining:2,available:true})
})
it('does not infer processing coverage from finding or approval totals', () => {
  expect(fileCoverage({files:[{file:'a',hasFindings:true,approved:10,verified:2}]})).toMatchObject({processed:null,remaining:null,available:false})
  expect(fileCoverage({counts:{withFindings:4,processed:3,remaining:3}})).toMatchObject({withFindings:4,processed:null,remaining:null,available:false})
  expect(fileCoverage({counts:{withFindings:4,processed:2,remaining:2}})).toMatchObject({withFindings:4,processed:2,remaining:2})
})
it('shows a saved baseline and defines processed separately from remediation success', async () => {
  const onSelect = vi.fn()
  await mount(<FileCoverage evidence={{counts:{withFindings:11,processed:5,remaining:6},baseline:{withFindings:11,processed:0,remaining:11}}} onSelect={onSelect}/>)
  expect(container.textContent).toContain('5 of 11 files with findings')
  expect(container.textContent).toContain('Before: 11')
  expect(container.textContent).toContain('Since start: −5')
  expect(container.textContent).toContain('does not mean fully remediated, verified, or published')
  await act(async () => container.querySelector('button').click())
  expect(onSelect).toHaveBeenCalledWith('withFindings')
})
it('animates signed decreases once, with no delta on initial render', async () => {
  vi.useFakeTimers()
  window.matchMedia = vi.fn(() => ({matches:true}))
  await mount(<BidirectionalKpiCounter value={9}/>)
  expect(container.textContent).toBe('9')
  await act(async () => root.render(<BidirectionalKpiCounter value={5}/>))
  expect(container.textContent).toBe('5−4')
  await act(async () => vi.advanceTimersByTime(2001))
  expect(container.textContent).toBe('5')
})
it('shows unknown coverage and unavailable baseline for historical runs', async () => {
  await mount(<FileCoverage evidence={{available:false}}/>)
  expect(container.textContent).toContain('Recorded processing coverage is unavailable for this run.')
  expect(container.querySelectorAll('.kpi-comparison')).toHaveLength(3)
  expect(container.querySelector('.kpi-comparison').textContent).toBe('Before unavailable')
  expect(container.querySelector('.coverage-verified strong').textContent).toBe('—')
})
it('clears transient delta when animation is turned off', async () => {
  vi.useFakeTimers()
  window.matchMedia = vi.fn(() => ({matches:true}))
  await mount(<BidirectionalKpiCounter value={9}/>)
  await act(async () => root.render(<BidirectionalKpiCounter value={5}/>))
  expect(container.textContent).toBe('5−4')
  await act(async () => root.render(<BidirectionalKpiCounter value={5} animate={false}/>))
  expect(container.textContent).toBe('5')
})

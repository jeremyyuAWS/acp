import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
import { createTestRoot, unmountAll } from './testRoots.js'
const getScan = vi.hoisted(() => vi.fn())
vi.mock('./api.js', () => ({ getScan }))
import useReleaseReadinessRefresh from './useReleaseReadinessRefresh.js'
import Access from './RemediationReleaseAccess.jsx'
afterEach(async () => { await unmountAll(); vi.useRealTimers(); vi.resetAllMocks() })
const file = (name, extra = {}) => ({ file: name, compliant: true, corrected_sha256: 'v1', remediated_at: '2026-09-09', ...extra })
it('offers Release beside unfinished documents but excludes absent verification and delivered copies', async () => {
  const { root, container } = createTestRoot(); const navigate = vi.fn()
  await act(async () => root.render(<Access files={[file('ready.pdf'), file('processing.pdf',{compliant:false}), file('uncorrected.pdf',{remediated_at:null}), file('unknown.pdf',{corrected_sha256:null}), file('delivered.pdf',{published_at:'2026-09-10'})]} onNavigate={navigate} />))
  expect(container.textContent).toContain('2 saved copies')
  expect(container.textContent).toContain('You do not need to open the HITL panel')
  await act(async () => container.querySelector('button').click())
  expect(navigate).toHaveBeenCalledWith('publish')
  const source = readFileSync(join(import.meta.dirname, 'Remediate.jsx'), 'utf8')
  expect(source.indexOf('<RemediationReleaseAccess')).toBeGreaterThan(source.indexOf('live={<>'))
  expect(source).not.toContain('Continue to Release')
})
it('allows going to Release before a saved copy exists without claiming it is ready', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(<Access files={[{file:'assessed.pdf',compliant:true}]} />))
  expect(container.textContent).toContain('Continue to Release')
  expect(container.textContent).not.toContain('available to publish')
  await act(async () => root.render(<Access files={[file('ready.pdf')]} readOnly />))
  expect(container.textContent).toBe('')
})
it('refreshes on opening and material changes, coalesces bursts, and ignores heartbeats and prior-run reads', async () => {
  vi.useFakeTimers(); const received=vi.fn(); const {root}=createTestRoot()
  getScan.mockResolvedValue({run:{id:'s'},files:[]})
  function Harness({run='s',value=1,revision=1,enabled=true}) { useReleaseReadinessRefresh({runId:run,enabled,snapshot:{scan_id:run,revision,documents:{completed:value}},onScan:received});return null }
  await act(async()=>root.render(<Harness />))
  await act(async()=>vi.advanceTimersByTimeAsync(1))
  expect(getScan).toHaveBeenCalledTimes(1)
  await act(async()=>root.render(<Harness revision={99} />))
  await act(async()=>vi.advanceTimersByTimeAsync(6000))
  expect(getScan).toHaveBeenCalledTimes(1)
  await act(async()=>root.render(<Harness value={2} />))
  await act(async()=>vi.advanceTimersByTimeAsync(1))
  await act(async()=>root.render(<Harness value={3} />))
  await act(async()=>root.render(<Harness value={4} />))
  expect(getScan).toHaveBeenCalledTimes(2)
  await act(async()=>vi.advanceTimersByTimeAsync(5000))
  expect(getScan).toHaveBeenCalledTimes(3)
  let old;getScan.mockImplementation(()=>new Promise(r=>{old=r}))
  await act(async()=>root.render(<Harness value={5} />))
  await act(async()=>vi.advanceTimersByTimeAsync(5000))
  await act(async()=>root.render(<Harness run="other" enabled={false} />))
  received.mockClear();await act(async()=>old({run:{id:'s'},files:[file('late.pdf')]}))
  expect(received).not.toHaveBeenCalled()
})

it('waits safely while no account or scan snapshot has loaded', async () => {
  const { root } = createTestRoot()
  function Empty() { useReleaseReadinessRefresh({ runId: undefined, enabled: false, snapshot: null, onScan: vi.fn() }); return null }
  await act(async () => root.render(<Empty />))
  expect(getScan).not.toHaveBeenCalled()
})

it.each([401, 403, 404])('stops automatic reads after access/run rejection %s', async status => {
  vi.useFakeTimers(); const { root } = createTestRoot()
  getScan.mockRejectedValue(Object.assign(new Error('Unavailable'), { status }))
  function Denied() { useReleaseReadinessRefresh({ runId: 's', enabled: true, snapshot: { scan_id: 's' }, onScan: vi.fn() }); return null }
  await act(async () => root.render(<Denied />))
  await act(async () => vi.advanceTimersByTimeAsync(30000))
  expect(getScan).toHaveBeenCalledTimes(1)
})

import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import useRunAiApproval from './useRunAiApproval.js'
import { getRunAiApproval, setRunAiApproval } from './api.js'
vi.mock('./api.js', () => ({ getRunAiApproval: vi.fn(), setRunAiApproval: vi.fn() }))
afterEach(async () => { await unmountAll(); vi.resetAllMocks() })
function View({ run = 'run' }) {
  const state = useRunAiApproval('scan', run)
  return <><input type="checkbox" role="switch" checked={state.enabled === true} disabled={!state.change || state.saving}
    onChange={event => state.change?.(event.target.checked)} /><span>{state.error}</span>{state.notice && <p data-notice="true">Confirmed automatic approval</p>}</>
}
it('changes only after the saved response and binds consent to the current source revision', async () => {
  getRunAiApproval.mockResolvedValue({ enabled: false, revision: 2, source_revision: 'source' })
  let finish
  setRunAiApproval.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const { root, container } = createTestRoot()
  await act(async () => root.render(<View />))
  const control = container.querySelector('input')
  await act(async () => control.click())
  expect(control.checked).toBe(false)
  expect(container.querySelector('[data-notice]')).toBeNull()
  expect(control.disabled).toBe(true)
  expect(setRunAiApproval).toHaveBeenCalledWith('scan', 'run', { enabled: true, expected_revision: 2, expected_source_revision: 'source' })
  await act(async () => finish({ enabled: true, revision: 3, source_revision: 'source' }))
  expect(control.checked).toBe(true)
  expect(container.querySelector('[data-notice]')).not.toBeNull()
  expect(control.disabled).toBe(false)
})
it('recovers a lost save response by rereading the durable value', async () => {
  getRunAiApproval.mockResolvedValueOnce({ enabled: false, revision: 0, source_revision: 'source' })
    .mockResolvedValue({ enabled: true, revision: 1, source_revision: 'source' })
  setRunAiApproval.mockRejectedValue(new Error('Connection lost'))
  const { root, container } = createTestRoot()
  await act(async () => root.render(<View />))
  await act(async () => container.querySelector('input').click())
  expect(container.querySelector('input').checked).toBe(true)
  expect(container.textContent).toContain('Connection lost')
  expect(container.querySelector('[data-notice]')).toBeNull()
})

it('does not notify for an already enabled loaded setting or a refused save', async () => {
  getRunAiApproval.mockResolvedValue({enabled:true,revision:1,source_revision:'source'})
  const {root,container}=createTestRoot();await act(async()=>root.render(<View/>))
  expect(container.querySelector('[data-notice]')).toBeNull()
  getRunAiApproval.mockResolvedValue({enabled:false,revision:2,source_revision:'source'})
  await act(async()=>root.render(<View run="new-run"/>))
  setRunAiApproval.mockRejectedValue(new Error('Save refused'))
  await act(async()=>container.querySelector('input').click())
  expect(container.querySelector('input').checked).toBe(false)
  expect(container.querySelector('[data-notice]')).toBeNull()
  expect(container.textContent).toContain('Save refused')
})
it('discards late enable confirmation after the user switches runs',async()=>{
 getRunAiApproval.mockResolvedValue({enabled:false,revision:1,source_revision:'source'})
 let finish;setRunAiApproval.mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
 const {root,container}=createTestRoot();await act(async()=>root.render(<View/>))
 await act(async()=>container.querySelector('input').click())
 await act(async()=>root.render(<View run="other-run"/>))
 await act(async()=>finish({enabled:true,revision:2,source_revision:'source'}))
 expect(container.querySelector('input').checked).toBe(false)
 expect(container.querySelector('[data-notice]')).toBeNull()
})

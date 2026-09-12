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
    onChange={event => state.change?.(event.target.checked)} /><span>{state.error}</span></>
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
  expect(control.disabled).toBe(true)
  expect(setRunAiApproval).toHaveBeenCalledWith('scan', 'run', { enabled: true, expected_revision: 2, expected_source_revision: 'source' })
  await act(async () => finish({ enabled: true, revision: 3, source_revision: 'source' }))
  expect(control.checked).toBe(true)
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
})

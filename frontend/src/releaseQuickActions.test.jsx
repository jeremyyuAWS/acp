import { createElement as h, act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
const api = vi.hoisted(() => ({ planReleaseContinuation: vi.fn(), authorizeReleaseContinuation: vi.fn(), getReleaseContinuation: vi.fn(), resumeReleaseContinuation: vi.fn() }))
vi.mock('./api.js', () => api)
import Quick from './ReleaseQuickActions.jsx'
const plan = { id: 'fixed-intent', status: 'draft', intent: { destination: { folder_name: 'Approved folder' }, files: {
  'ready.pdf': { ready: true, rows: [], blockers: [] },
  'changes.pdf': { rows: [{ id: 'v1', rule_id: '1.1.1', authorize: true, proposals: [{ proposed_value: 'Exact draft' }] }], blockers: [] },
  'manual.pdf': { rows: [], blockers: ['Manual repair required'] },
} } }
const flush = async () => act(async () => { await Promise.resolve() })
const click = async el => { await act(async () => el.click()); await flush() }
async function mount(extra = {}, response = plan) {
  api.planReleaseContinuation.mockResolvedValue(response); api.getReleaseContinuation.mockResolvedValue(null)
  api.authorizeReleaseContinuation.mockResolvedValue({ ...plan, status: 'waiting', progress: {} })
  const props = { runId: 'run-1', files: ['ready.pdf', 'changes.pdf', 'manual.pdf'].map(file => ({ file, corrected_sha256: 'v1' })),
    ready: [{ file: 'ready.pdf' }], destination: { folder_id: 'fixed', folder_name: 'Approved folder' }, destinationLabel: 'Approved folder', onReady: vi.fn(), ...extra }
  const { container, root } = createTestRoot()
  await act(async () => root.render(h(Quick, props))); await flush()
  return { container, props, button: text => [...container.querySelectorAll('button')].find(b => b.textContent.includes(text)),
    render: async update => { await act(async () => root.render(h(Quick, { ...props, ...update }))); await flush() } }
}
afterEach(async () => { await unmountAll(); vi.useRealTimers(); vi.resetAllMocks() })
it('publishes only ready files without opening details or reviewing others', async () => {
  const v = await mount(); await click(v.button('Publish ready files (1)'))
  expect(v.props.onReady).toHaveBeenCalledWith(['ready.pdf'])
  expect(api.authorizeReleaseContinuation).not.toHaveBeenCalled()
  expect([...v.container.querySelectorAll('details')].every(d => !d.open)).toBe(true)
})
it('authorizes the exact server plan once with optional inspection', async () => {
  const v = await mount(); expect(v.container.textContent).toContain('Destination: Approved folder')
  expect(v.container.textContent).toContain('Manual repair required')
  let resolve; api.authorizeReleaseContinuation.mockImplementation(() => new Promise(r => { resolve = r }))
  const button = v.button('Approve eligible changes'); await click(button); await click(button)
  expect(api.authorizeReleaseContinuation).toHaveBeenCalledTimes(1)
  expect(api.authorizeReleaseContinuation).toHaveBeenCalledWith('run-1', 'fixed-intent')
  await act(async () => resolve({ ...plan, status: 'waiting', progress: {} }))
})
it('invalidates the plan when destination changes', async () => {
  const v = await mount(); api.planReleaseContinuation.mockImplementation(() => new Promise(() => {}))
  await v.render({ destination: { folder_id: 'changed', folder_name: 'New folder' } })
  expect(v.button('Approve eligible changes').disabled).toBe(true)
  expect(api.authorizeReleaseContinuation).not.toHaveBeenCalled()
})
it('keeps ready-only publishing available while the continuation runs', async () => {
  const v = await mount(); api.getReleaseContinuation.mockResolvedValue({ ...plan, status: 'waiting', progress: { 'changes.pdf': { state: 'applying', message: 'Applying' } } })
  await v.render({ runId: 'restored-run' })
  expect(v.button('Publish ready files').disabled).toBe(false)
  expect(v.button('Approve eligible changes').disabled).toBe(true)
  expect(v.container.textContent).toContain('Progress is saved')
})
it('restores partial delivery and retries only the original intent', async () => {
  const v = await mount(); api.getReleaseContinuation.mockResolvedValue({ ...plan, status: 'completed', progress: {
    'ready.pdf': { state: 'published', message: 'Delivered' }, 'changes.pdf': { state: 'failed', message: 'Reconnect' }, 'manual.pdf': { state: 'blocked', message: 'Manual repair required' },
  } })
  await v.render({ runId: 'restored-run' }); expect(v.container.textContent).toContain('1 delivered · 0 in progress · 2 need attention')
  api.resumeReleaseContinuation.mockResolvedValue({ ...plan, status: 'waiting' }); await click(v.button('Retry failed delivery'))
  expect(api.resumeReleaseContinuation).toHaveBeenCalledWith('restored-run', 'fixed-intent')
})
it('prevents writes in read-only replay', async () => {
  const v = await mount({ readOnly: true }); expect(v.button('Publish ready files').disabled).toBe(true)
  expect(api.planReleaseContinuation).not.toHaveBeenCalled(); expect(api.authorizeReleaseContinuation).not.toHaveBeenCalled()
})

it('shows loading separately from known zero eligibility and preserves ready-only publishing', async () => {
  let resolve
  const v = await mount({}, new Promise(r => { resolve = r }))
  expect(v.container.textContent).toContain('Checking which proposals')
  expect(v.container.textContent).not.toContain('Other files do not hold eligible')
  expect(v.button('Publish ready files').disabled).toBe(false)
  await click(v.button('Publish ready files'))
  expect(v.props.onReady).toHaveBeenCalledWith(['ready.pdf'])
  await act(async () => resolve({ ...plan, intent: { files: {} } }))
  expect(v.container.textContent).not.toContain('Checking which proposals')
  expect(v.container.textContent).toContain('Other files do not hold eligible')
})

it('bounds a stalled check, aborts it, retries explicitly, and ignores its late result', async () => {
  vi.useFakeTimers()
  let resolve
  const v = await mount({}, new Promise(r => { resolve = r }))
  const signal = api.planReleaseContinuation.mock.calls[0][4].signal
  await act(async () => vi.advanceTimersByTimeAsync(20000))
  expect(signal.aborted).toBe(true)
  expect(v.container.textContent).toContain('Eligibility could not be confirmed in time')
  expect(v.container.textContent).not.toContain('Checking which proposals')
  expect(v.button('Publish ready files').disabled).toBe(false)
  api.planReleaseContinuation.mockResolvedValue({ ...plan, intent: { files: {} } })
  await click(v.button('Refresh eligibility and status'))
  expect(v.container.textContent).toContain('Other files do not hold eligible')
  await act(async () => resolve(plan))
  expect(v.button('Approve eligible changes').disabled).toBe(true)
  expect(api.authorizeReleaseContinuation).not.toHaveBeenCalled()
})

it('shows failed eligibility as unknown with a retry instead of a known zero', async () => {
  const v = await mount()
  api.planReleaseContinuation.mockRejectedValue(new Error('Eligibility service unavailable'))
  await v.render({ folderName: 'New destination' })
  expect(v.container.textContent).toContain('Eligibility service unavailable')
  expect(v.container.textContent).not.toContain('Other files do not hold eligible')
  expect(v.button('Refresh eligibility and status')).toBeDefined()
  expect(v.button('Publish ready files').disabled).toBe(false)
})


it('keeps both actions visible outside disclosure panels at zero readiness with linked reasons', async () => {
  const v = await mount({ ready: [], readyReasons: ['Verification incomplete. Resolve findings in Remediate.'] }, { ...plan, intent: { files: {} } })
  expect(v.container.querySelector('h3').textContent).toBe('Release actions')
  for (const label of ['Publish ready files (0)', 'Approve eligible changes']) {
    const button = v.button(label)
    expect(button.disabled).toBe(true)
    expect(button.closest('details')).toBeNull()
    expect(v.container.querySelector(`[id="${button.getAttribute('aria-describedby')}"]`).textContent).toBeTruthy()
    await click(button)
  }
  expect(v.container.textContent).toContain('Verification incomplete')
  expect(v.container.textContent).toContain('No complete, versioned proposals are ready')
  expect(v.props.onReady).not.toHaveBeenCalled()
  expect(api.authorizeReleaseContinuation).not.toHaveBeenCalled()
})

it('keeps both unavailable actions visible during loading and empty scope', async () => {
  const v = await mount({ ready: [] }, new Promise(() => {}))
  expect(v.button('Approve eligible changes').disabled).toBe(true)
  expect(v.container.textContent).toContain('Checking which proposals')
  await v.render({ files: [], ready: [] })
  expect(v.button('Publish ready files').disabled).toBe(true)
  expect(v.button('Approve eligible changes').disabled).toBe(true)
  expect(v.container.textContent).toContain('No files are selected in this scope')
})

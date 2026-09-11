import { createElement as h, act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
const api = vi.hoisted(() => ({ planReleaseContinuation: vi.fn(), authorizeReleaseContinuation: vi.fn(), getReleaseContinuation: vi.fn(), resumeReleaseContinuation: vi.fn(), setDriveToken: vi.fn() }))
vi.mock('./api.js', () => api)
vi.mock('./driveAuth.js', () => ({reconnectDriveForRelease: vi.fn().mockResolvedValue('grant')}))
import { reconnectDriveForRelease } from './driveAuth.js'
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
  const button = v.button('Approve eligible changes')
  expect(button.closest('details')).toBeNull()
  expect(button.closest('.release-quick-step').querySelector('h4').textContent).toContain('3 Publish copies')
  await click(button); await click(button)
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


it('keeps publishing and approval visible without opening any disclosure, with linked reasons', async () => {
  const v = await mount({ ready: [], readyReasons: ['Verification incomplete. Resolve findings in Remediate.'] }, { ...plan, intent: { files: {} } })
  expect(v.container.querySelector('h3').textContent).toBe('Publish your documents')
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
it('shows the durable timestamp folder in the destination before authorizing', async () => {
  const v = await mount({ folderName: 'Stale form name' }, { ...plan, intent: { ...plan.intent, release_folder_name: '2026-09-09 15-00 PDT' } })
  expect(v.container.textContent).toContain('Approved folder / Remediated / 2026-09-09 15-00 PDT')
  expect(v.container.textContent).not.toContain('Stale form name')
})

it('shows three ordered steps and publishes only checked ready copies', async () => {
  const v = await mount({ ready: [{ file: 'ready.pdf' }, { file: 'changes.pdf' }] })
  expect([...v.container.querySelectorAll('h4')].map(h => h.textContent)).toEqual(['1 Choose files', '2 Confirm destination', '3 Publish copies'])
  await click(v.container.querySelector('[aria-label="Publish changes.pdf"]'))
  await click(v.button('Publish ready files (1)'))
  expect(v.props.onReady).toHaveBeenCalledWith(['ready.pdf'])
  expect(v.container.querySelector('[aria-label="Publish manual.pdf"]').disabled).toBe(true)
  await click(v.container.querySelector('[aria-label="Publish ready.pdf"]'))
  expect(v.button('Publish ready files (0)').disabled).toBe(true)
  expect(v.container.textContent).toContain('Select at least one ready file above')
})
it('drops old file exclusions when the scan changes', async () => {
  const v = await mount()
  await click(v.container.querySelector('[aria-label="Publish ready.pdf"]'))
  await v.render({ runId: 'another-scan' })
  expect(v.container.querySelector('[aria-label="Publish ready.pdf"]').checked).toBe(true)
})

it('replaces the empty publish action with completion and the recorded folder link', async () => {
  const v = await mount({ files: [{ file: 'ready.pdf' }], ready: [], fileStates: { 'ready.pdf': { status: 'released', label: 'Delivered' } }, providerLabel: 'SharePoint', publishedFolders: [{ id: 'folder', url: 'https://example.test/published' }] })
  expect(v.container.querySelector('h3').textContent).toBe('Publishing complete')
  expect(v.container.textContent).toContain('All files are already published.')
  expect(v.container.querySelector('.release-published-message a').href).toBe('https://example.test/published')
  expect(v.container.querySelector('.release-published-message a').textContent).toContain('SharePoint')
  expect(v.container.querySelector('.release-quick-file--delivered input').disabled).toBe(true)
  expect(v.button('All files published').disabled).toBe(true)
  expect(v.props.onReady).not.toHaveBeenCalled()
})
it('mutes only delivered files and keeps unfinished files selectable', async () => {
  const v = await mount({ files: [{ file: 'ready.pdf' }, { file: 'sent.pdf' }], fileStates: { 'sent.pdf': { status: 'released', label: 'Delivered' } }, providerLabel: 'Google Drive' })
  expect(v.container.querySelectorAll('.release-quick-file--delivered')).toHaveLength(1)
  expect(v.container.textContent).toContain('1 file is already published.')
  expect(v.container.querySelector('.release-published-message a')).toBeNull()
  expect(v.container.textContent).toContain('folder link is not available yet')
  await click(v.button('Publish ready files (1)'))
  expect(v.props.onReady).toHaveBeenCalledWith(['ready.pdf'])
})

it('shows publication feedback beside the disabled in-flight action', async () => {
  const v = await mount({ publishing: true, announcement: 'Publishing your selected copies. Please wait for confirmation.' })
  expect(v.button('Publishing copies').disabled).toBe(true)
  expect(v.container.querySelector('.release-quick-action [role="status"]').textContent).toContain('Please wait for confirmation')
  await click(v.button('Publishing copies'))
  expect(v.props.onReady).not.toHaveBeenCalled()
})

it('reconnects Drive and resumes the saved manual authorization without approving again', async () => {
 reconnectDriveForRelease.mockResolvedValue('grant')
 const v=await mount()
 api.getReleaseContinuation.mockResolvedValue({...plan,status:'completed',requires_reconnect:true,progress:{'ready.pdf':{state:'failed',message:'Reconnect Drive'}}})
 await v.render({runId:'saved-run'})
 api.resumeReleaseContinuation.mockResolvedValue({...plan,status:'waiting',requires_reconnect:false})
 await click(v.button('Reconnect Google Drive and resume'))
 expect(api.setDriveToken).toHaveBeenCalledWith('grant')
 expect(api.resumeReleaseContinuation).toHaveBeenCalledWith('saved-run','fixed-intent')
 expect(api.authorizeReleaseContinuation).not.toHaveBeenCalled()
})

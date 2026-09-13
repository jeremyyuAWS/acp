import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import DriveReleaseReconnect from './DriveReleaseReconnect.jsx'
import { _resetRecoveryAttempts } from './useAutomaticDeliveryRecovery.js'
import { _resetAuthEpoch } from './apiIdentity.js'
vi.mock('./driveAuth.js', () => ({ reconnectDriveForRelease: vi.fn() }))
vi.mock('./spAuth.js', () => ({ refreshSPToken: vi.fn() }))
vi.mock('./api.js', () => ({ setDriveToken: vi.fn(), setSPToken: vi.fn() }))
afterEach(async () => {
  await unmountAll(); sessionStorage.clear(); _resetRecoveryAttempts(); _resetAuthEpoch(); vi.resetAllMocks()
})
const saved = { id: 'permission', run_id: 'original-run', revision: 1, status: 'blocked',
  can_resume: true, requires_reconnect: false, source_revision: 'original-source',
  files: ['document.docx'], destination: { folder_id: 'saved-folder' } }
async function mount(provider, onResume, authorization = saved) {
  const { root } = createTestRoot()
  await act(async () => root.render(createElement(DriveReleaseReconnect, {
    provider, scanId: 'scan', owner: 'owner', authorizationId: saved.id,
    authorization, requiresReconnect: false, onResume, onRefresh: vi.fn(),
  })))
}
it.each(['sharepoint', 'drive'])('closing %s tab while resume is pending does not resend on reopening', async provider => {
  let finish
  const resume = vi.fn(() => new Promise(resolve => { finish = resolve }))
  await mount(provider, resume)
  expect(resume).toHaveBeenCalledOnce()
  await unmountAll(); _resetRecoveryAttempts()
  await mount(provider, resume)
  expect(resume).toHaveBeenCalledOnce()
  await act(async () => finish({ accepted: true }))
  expect(resume).toHaveBeenCalledOnce()
  expect(document.querySelector('.release-recovery-banner').textContent).toContain('Delivery recovery is unconfirmed')
  expect(document.querySelector('.release-recovery-banner').textContent).toContain('refreshing the saved status')
})
it.each(['sharepoint', 'drive'])('completed %s authorization clears recovery UI without another request', async provider => {
  const resume = vi.fn().mockResolvedValue({ accepted: true })
  await mount(provider, resume)
  await unmountAll(); _resetRecoveryAttempts()
  await mount(provider, resume, { ...saved, status: 'completed', can_resume: false })
  expect(resume).toHaveBeenCalledOnce()
  expect(document.querySelector('.release-recovery-banner')).toBeNull()
})

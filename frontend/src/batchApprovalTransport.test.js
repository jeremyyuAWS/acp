import { it, expect, vi, afterEach } from 'vitest'
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules() })
it('sends frozen snapshot/source/version and preserves a retry request identity', async () => {
  vi.stubEnv('VITE_SIM', 'false'); vi.resetModules()
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ status: 'approved' }) }))
  vi.stubGlobal('fetch', fetcher)
  const { updateHitlItem } = await import('./api.js')
  const options = { approvedValues: ['A', 'B'], requestId: 'stable-request', expectedVersion: 2,
    expectedProposalSnapshotIds: ['first', 'second'], expectedSourceRevision: 'assessed-source' }
  await updateHitlItem('frozen-item', 'approved', null, 'A', options)
  await updateHitlItem('frozen-item', 'approved', null, 'A', options)
  expect(fetcher.mock.calls.map(([, r]) => JSON.parse(r.body))).toEqual([expect.objectContaining({
    expected_proposal_snapshot_ids: ['first', 'second'], expected_source_revision: 'assessed-source',
    expected_version: 2, request_id: 'stable-request', approved_values: ['A', 'B'],
  }), expect.objectContaining({ request_id: 'stable-request' })])
})

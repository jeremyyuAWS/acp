import { afterEach, expect, it, vi } from 'vitest'
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.resetModules() })
it('sends explicit remaining-issues consent and the same artifact digest to preview and publication', async () => {
  vi.stubEnv('VITE_SIM', 'false'); vi.resetModules()
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
  vi.stubGlobal('fetch', fetch)
  const { previewReleaseDestination, publishAllFiles } = await import('./api.js')
  const options = { allowRemainingIssues: true, expectedArtifacts: { 'partial.docx': 'saved' } }
  await previewReleaseDestination('s', ['partial.docx'], 'Delivery', true, null, options)
  await publishAllFiles('s', ['partial.docx'], 'Delivery', options)
  for (const [, request] of fetch.mock.calls) expect(JSON.parse(request.body)).toMatchObject({
    allow_remaining_issues: true, expected_artifacts: { 'partial.docx': 'saved' }, files: ['partial.docx'],
  })
  await publishAllFiles('s', ['verified.docx'])
  expect(JSON.parse(fetch.mock.lastCall[1].body)).not.toHaveProperty('allow_remaining_issues')
})

import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createTestRoot, unmountAll } from './testRoots.js'
import { noteAuthChange, _resetAuthEpoch } from './apiIdentity.js'
import { getActiveWorkflows, getActiveScan, refreshScanSPToken, setSPToken } from './api.js'
import { refreshSPToken } from './spAuth.js'
vi.mock('./api.js', async importActual => ({ ...(await importActual()), getActiveWorkflows: vi.fn(), getActiveScan: vi.fn(), refreshScanSPToken: vi.fn(), setSPToken: vi.fn() }))
vi.mock('./spAuth.js', () => ({ refreshSPToken: vi.fn() }))
globalThis.__BUILD_TIME__ = '2026-09-14T00:00:00.000Z'
globalThis.__BUILD_VERSION__ = '2026.9.14'
const { useSharePointWorkflowKeepalive } = await import('./App.jsx')
function Harness(props) { useSharePointWorkflowKeepalive(props); return null }
afterEach(async () => { await unmountAll(); vi.resetAllMocks(); vi.useRealTimers(); sessionStorage.clear(); _resetAuthEpoch() })
async function mount(extra = {}) {
  getActiveWorkflows.mockResolvedValue({active_workflows:[{source:'sharepoint',scan_id:'release'},{source:'sharepoint',scan_id:'release'},{source:'drive',scan_id:'other'}]})
  refreshSPToken.mockResolvedValue('renewed'); refreshScanSPToken.mockResolvedValue({})
  const props = {hasSPToken:true,owner:'owner',reconnectRevision:0,setActiveWorkflows:vi.fn(),setTokenRefreshError:vi.fn(),...extra}
  const {root} = createTestRoot()
  const render = overrides => act(async () => root.render(createElement(Harness,{...props,...overrides})))
  await render({}); return {props,render}
}
it('reconnect refreshes the completed scan release immediately while token presence stays true',async () => {
  vi.useFakeTimers(); const v = await mount()
  expect(refreshScanSPToken).toHaveBeenCalledExactlyOnceWith('release')
  await v.render({reconnectRevision:1})
  expect(refreshScanSPToken).toHaveBeenCalledTimes(2)
  expect(refreshSPToken).toHaveBeenLastCalledWith({interactive:false,persist:false})
  expect(setSPToken).toHaveBeenLastCalledWith('renewed')
  expect(sessionStorage.getItem('sp_token')).toBe('renewed')
  expect(getActiveScan).not.toHaveBeenCalled()
  await act(async () => vi.advanceTimersByTime(20*60*1000))
  expect(refreshScanSPToken).toHaveBeenCalledTimes(3)
})
it.each(['logout','owner','epoch','unmount','reconnect'])('rejects a late silent grant after %s',async change => {
  const v = await mount(); vi.clearAllMocks(); let finish
  refreshSPToken.mockImplementationOnce(() => new Promise(resolve => {finish=resolve}))
  await v.render({reconnectRevision:1})
  if(change==='logout') await v.render({hasSPToken:false,reconnectRevision:1})
  if(change==='owner') await v.render({owner:'next',hasSPToken:false,reconnectRevision:1})
  if(change==='epoch') noteAuthChange('owner','next')
  if(change==='unmount') await unmountAll()
  if(change==='reconnect') {refreshSPToken.mockResolvedValue('newest'); await v.render({reconnectRevision:2})}
  const count = refreshScanSPToken.mock.calls.length
  sessionStorage.removeItem('sp_token'); setSPToken.mockClear(); v.props.setTokenRefreshError.mockClear()
  await act(async () => finish('stale'))
  expect(setSPToken).not.toHaveBeenCalled(); expect(sessionStorage.getItem('sp_token')).toBeNull()
  expect(refreshScanSPToken).toHaveBeenCalledTimes(count); expect(v.props.setTokenRefreshError).not.toHaveBeenCalled()
})
it('discards owner-scoped workflow lookup completed after logout',async () => {
  const v = await mount(); vi.clearAllMocks(); let finish
  getActiveWorkflows.mockImplementationOnce(() => new Promise(resolve => {finish=resolve}))
  await v.render({reconnectRevision:1}); await v.render({hasSPToken:false,reconnectRevision:1})
  await act(async () => finish({active_workflows:[{source:'sharepoint',scan_id:'old'}]}))
  expect(refreshSPToken).not.toHaveBeenCalled(); expect(v.props.setActiveWorkflows).not.toHaveBeenCalled()
})
it('Microsoft source success advances the revision used by the mounted keepalive',() => {
  const app = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'App.jsx'),'utf8')
  const branch = app.slice(app.indexOf("} else if (provider === 'microsoft')"),app.indexOf('// Time-travel:'))
  expect(branch).toContain('setSPReconnectRevision((revision) => revision + 1)')
  expect(app).toContain('reconnectRevision: spReconnectRevision')
})

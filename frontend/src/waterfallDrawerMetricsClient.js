import { getRealtimeStreamRequest } from './api.js'
import { apiBase, authEpoch } from './apiIdentity.js'
import { SIM } from './sim.js'

export const drawerMetricScope = ({ stage = null, provider = null, model = null } = {}) => ({ stage, provider, model })
export async function getWaterfallDrawerMetrics(scanId, batchId, scope, signal) {
  if (SIM) return null
  const expected = drawerMetricScope(scope)
  const epoch = authEpoch()
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(expected)) if (value != null) query.set(key, value)
  const { headers } = getRealtimeStreamRequest()
  const response = await fetch(`${apiBase()}/scans/${encodeURIComponent(scanId)}/remediation/waterfall/${encodeURIComponent(batchId)}/metrics?${query}`, { headers, signal, cache: 'no-store' })
  if (!response.ok) throw Object.assign(new Error('Recorded stage metrics could not be loaded.'), { status: response.status })
  const data = await response.json()
  if (epoch !== authEpoch() || data.scan_id !== scanId || data.batch_id !== batchId
      || JSON.stringify(drawerMetricScope(data.scope)) !== JSON.stringify(expected)) throw new Error('The selected account, run, or stage changed.')
  return data
}

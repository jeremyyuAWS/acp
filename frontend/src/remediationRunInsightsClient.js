import { getRealtimeStreamRequest } from './api.js'
import { apiBase, authEpoch } from './apiIdentity.js'
import { SIM } from './sim.js'

export async function getRunInsights(scanId, batchId, signal, offset = 0) {
  if (SIM) return null
  const epoch = authEpoch()
  const { headers } = getRealtimeStreamRequest()
  const response = await fetch(`${apiBase()}/scans/${encodeURIComponent(scanId)}/remediation/insights/${encodeURIComponent(batchId)}?offset=${offset}&limit=100`, { headers, signal, cache: 'no-store' })
  if (!response.ok) throw new Error('Saved model history could not be loaded.')
  const result = await response.json()
  if (epoch !== authEpoch() || result.scan_id !== scanId || result.batch_id !== batchId) throw new Error('The selected account or run changed.')
  return result
}

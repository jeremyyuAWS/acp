import { getRealtimeStreamRequest } from './api.js'
import { apiBase, authEpoch } from './apiIdentity.js'
import { SIM } from './sim.js'

export async function getWaterfall(scanId, batchId, signal) {
  if (SIM) return null
  const epoch = authEpoch()
  // Reuse the authenticated request descriptor so Microsoft retains its provider
  // header. Never reconstruct authentication from the token alone.
  const { headers } = getRealtimeStreamRequest()
  const response = await fetch(`${apiBase()}/scans/${encodeURIComponent(scanId)}/remediation/waterfall/${encodeURIComponent(batchId)}`, {
    headers, signal, cache: 'no-store',
  })
  if (!response.ok) throw new Error('Waterfall activity could not be refreshed.')
  const result = await response.json()
  if (epoch !== authEpoch()) throw new Error('Account changed.')
  if (result.scan_id !== scanId || result.batch_id !== batchId) throw new Error('Run changed.')
  return result
}

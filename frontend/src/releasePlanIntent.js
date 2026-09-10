import { enableAutomaticRelease, getAutomaticRelease } from './api.js'

export const releasePlanKey = (scanId, files) => JSON.stringify([scanId, [...new Set(files)].sort()])

// Remediation has already been accepted. Release failure must never turn this into
// a remediation submission failure or cause a second start request.
export async function authorizeAcceptedRelease(scanId, files, accepted, intent, client = { enable: enableAutomaticRelease, get: getAutomaticRelease }) {
  if (!intent) return ''
  const missing = 'Remediation started. Automatic release was not enabled because its accepted run could not be confirmed. Check Live before enabling it.'
  if (!Array.isArray(intent.files) || releasePlanKey(scanId, intent.files) !== releasePlanKey(scanId, files) || !intent.source_revision || !intent.destination?.folder_id || intent.key !== releasePlanKey(scanId, files) || !(accepted?.enqueued > 0) || !accepted.batch_id || accepted.scan_id !== scanId || accepted.snapshot_id !== intent.source_revision) return missing
  let request
  try {
    request = { run_id: accepted.batch_id, files: [...intent.files], destination: { ...intent.destination }, expected_source_revision: intent.source_revision, request_id: crypto.randomUUID(), allow_remaining_issues: intent.allow_remaining_issues === true, include_reports: intent.include_reports === true }
    await client.enable(scanId, request)
    return 'Remediation started. Automatic release is enabled for the selected files and destination. See Live for progress and Stop.'
  } catch {
    try {
      if (!request) throw new Error('No release request was sent')
      const status = await client.get(scanId, request.files)
      const saved = status?.authorization
      if (saved?.request_id === request.request_id && saved.run_id === request.run_id && saved.source_revision === request.expected_source_revision && (saved.allow_remaining_issues === true) === request.allow_remaining_issues && (saved.include_reports === true) === request.include_reports && ['active', 'waiting', 'blocked', 'completed'].includes(saved.status)) {
        return 'Remediation started. Automatic release was confirmed after refreshing its saved status. See Live for progress and Stop.'
      }
    } catch { /* Unknown results remain unconfirmed; never retry the write. */ }
    return 'Remediation started. Automatic release could not be confirmed. Check its status in Live before trying to enable it; remediation does not need to be started again.'
  }
}

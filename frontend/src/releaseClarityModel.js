// Release uses the same corrected-copy eligibility as POST /scans/{sid}/publish.
// A passing assessment or an uploaded certificate is not a delivery receipt.
export const hasCorrectedCopy = (file) => (file.compliant === true || file.compliant === 1) && Boolean(file.remediated_at)

export const hasSavedCorrectedCopy = (file) => Boolean(file.remediated_at && file.corrected_sha256)

export function deliveryIsCurrent(file, result, done = {}) {
  if (result && result.status !== 'published') return false
  if (result?.artifact_digest && file.corrected_sha256) return result.artifact_digest === `sha256:${file.corrected_sha256}`
  const publishedAt = result?.published_at || file.published_at
  if (!publishedAt) return result?.status === 'published' || done[file.file] === true
  const published = Date.parse(publishedAt)
  const corrected = Date.parse(file.remediated_at)
  if (!Number.isFinite(published)) return false
  return !file.remediated_at || (Number.isFinite(corrected) && published >= corrected)
}

export function releaseReadiness(file, { done = {}, results = {}, sourceState = () => undefined, pending = {}, processing = {}, blockers = {}, allowRemainingIssues = false } = {}) {
  const result = results[file.file]
  if (deliveryIsCurrent(file, result, done)) return { status: 'released', label: 'Delivered', reason: 'Delivery recorded. Originals unchanged.' }
  if (['queued', 'running'].includes(result?.status)) return { status: 'delivering', label: 'Delivering', reason: 'Release continues in the background. Return here for the receipt.' }
  if (sourceState(file) === 'stale') return { status: 'changed', label: 'Needs attention', reason: 'Source changed. Rescan before releasing this copy.' }
  if (sourceState(file) === 'unavailable') return { status: 'unreachable', label: 'Needs attention', reason: 'Source unreachable. Restore access and check again.' }
  if (processing[file.file]) return { status: 'applying', label: 'Processing', reason: `${processing[file.file]} approved fixes applying or awaiting verification. No further approval needed.` }
  if (allowRemainingIssues && !hasSavedCorrectedCopy(file)) return { status: 'attention', label: 'No saved copy', reason: 'No saved corrected copy is available to publish. This does not indicate an accessibility finding. Save a copy through Remediate first.' }
  if (allowRemainingIssues && hasSavedCorrectedCopy(file)) {
    if (blockers[file.file]) return { status: 'attention', label: 'Needs attention', reason: blockers[file.file] }
    if (!hasCorrectedCopy(file) || pending[file.file]) return { status: 'ready', label: 'Ready with remaining issues', reason: 'Publish the saved copy. Unresolved findings and unapproved suggestions remain recorded; this is not certification.' }
  }
  if (pending[file.file]) return { status: 'attention', label: 'Needs attention', reason: `${pending[file.file]} review items pending. Approve, apply and verify changes in Remediate → Review.` }
  if (!hasCorrectedCopy(file)) return { status: 'attention', label: 'Needs attention', reason: file.compliant === true || file.compliant === 1
    ? 'No verified corrected copy. Apply and verify changes in Remediate.'
    : file.compliant === false || file.compliant === 0 ? 'Verification incomplete. Resolve findings in Remediate and verify the corrected copy.' : 'Readiness unknown. Assess and verify this file before Release.' }
  if (blockers[file.file]) return { status: 'attention', label: 'Needs attention', reason: blockers[file.file] }
  if (result?.status === 'failed') return { status: 'failed', label: 'Needs attention', reason: result.explanation || 'Delivery failed. Review the destination and retry this file.' }
  return { status: 'ready', label: 'Ready', reason: 'Verified corrected copy awaiting Release.' }
}

export const canSelectRelease = (state) => ['ready', 'released', 'failed'].includes(state.status)

// The source-status endpoint overlays lifecycle states on freshness. Preserve its
// underlying timestamp/error evidence when the overlay says publish_pending or acp_newer.
export function releaseSourceState(row) {
  if (!row) return undefined
  if (row.error) return 'unavailable'
  const baseline = Date.parse(row.baseline), current = Date.parse(row.current)
  if (row.state === 'conflict' || (Number.isFinite(baseline) && Number.isFinite(current) && current > baseline)) return 'stale'
  return row.state
}

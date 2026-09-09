const rows = value => Array.isArray(value) ? value : []
const text = value => typeof value === 'string' && value.trim() ? value : null
export const attemptPurpose = value => ({ draft: 'First AI attempt', fallback: 'Fallback attempt', review: 'AI review', final_review: 'Final AI review' })[value] || 'Recorded attempt'
export const attemptStatus = value => ({ started: 'Final response not recorded', drafted: 'Output saved for consideration', unusable_response: 'Response could not be used', empty_response: 'No response content', refused: 'Provider declined the request', usage_unknown: 'Usage or charge is uncertain', rejected_before_dispatch: 'Stopped before dispatch', settlement_failed_or_breached: 'Charge needs reconciliation', provider_limit_exceeded: 'Provider limit reached', accepted: 'AI review accepted the suggestion', revision_requested: 'AI review requested changes', unable_to_judge: 'AI could not judge' })[value] || 'Status not recorded'
export const reviewVerdict = value => ({ accept: 'AI review accepted the suggestion', revise: 'AI review requested changes', unable: 'AI could not judge' })[value] || 'Review result not recorded'

export function attemptStory(data, file, { live = false } = {}) {
  const attempts = rows(data?.attempts).filter(item => text(item.file) && text(item.attempt_id))
  const proposals = rows(data?.proposals)
  const files = [...new Set([...attempts.map(item => item.file), ...proposals.map(item => text(item.file)).filter(Boolean)])].sort()
  const selected = attempts.filter(item => item.file === file)
  const groups = []
  for (const attempt of selected) {
    // Missing operation linkage remains its own record; file/model/time are never join keys.
    const key = text(attempt.operation_id) ? `operation:${attempt.operation_id}` : `attempt:${attempt.attempt_id}`
    let group = groups.find(item => item.key === key)
    if (!group) { group = { key, operationId: text(attempt.operation_id), attempts: [], receipts: [], proposals: [] }; groups.push(group) }
    group.attempts.push(attempt)
  }
  for (const group of groups) {
    const ids = new Set(group.attempts.map(item => item.attempt_id))
    group.proposals = proposals.filter(item => item.file === file && ids.has(item.attempt_id))
    group.receipts = rows(data?.review_receipts).filter(receipt => group.operationId && receipt.operation_id === group.operationId
      && text(receipt.proposal_sha256) && group.attempts.some(attempt => attempt.output_sha256 === receipt.proposal_sha256))
    // Review calls may use separate operation IDs. Only the receipt's explicit attempt IDs link them.
    const linkedReviewIds = new Set(group.receipts.flatMap(receipt => rows(receipt.review?.steps).map(step => step.attempt_id).filter(Boolean)))
    group.reviewAttempts = selected.filter(item => !ids.has(item.attempt_id) && linkedReviewIds.has(item.attempt_id))
    group.next = group.attempts.some(item => item.status === 'started')
      ? live ? 'Wait for the recorded response. This view refreshes while expanded and live updates are available.' : 'No final response was retained for this attempt. Inspect the run status before retrying.'
      : group.attempts.some(item => ['usage_unknown', 'settlement_failed_or_breached'].includes(item.status))
        ? 'Check the uncertain charge before retrying this work.'
        : group.proposals.some(item => rows(item.human_reviews).length > 0)
          ? 'Related human decisions already exist. Check remaining work and completion evidence in Review before repeating a decision.'
          : group.proposals.length || group.attempts.some(item => item.status === 'drafted')
          ? 'Inspect the saved suggestion and its review evidence in Review. An AI review does not approve or verify the change.'
          : 'Inspect the recorded reason. Remaining work may need a person or another permitted attempt.'
  }
  const linkedIds = new Set(groups.flatMap(group => group.proposals.map(item => item.snapshot_id)))
  return { files, groups, unlinkedProposals: proposals.filter(item => item.file === file && !linkedIds.has(item.snapshot_id)) }
}

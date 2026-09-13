// Approval is a run decision, independent of what is assessed and where copies are delivered.
export const APPROVAL_MODES = ['automatic', 'review', 'custom']
export function normalizeApprovalPolicy(value, selectedCriteria = []) {
  const mode = APPROVAL_MODES.includes(value?.mode) ? value.mode : 'review'
  const selected = new Set(selectedCriteria)
  const review = Array.isArray(value?.review_scs) ? value.review_scs : []
  return { mode, review_scs: mode === 'custom' ? [...new Set(review.filter(sc => selected.has(sc)))].sort() : [] }
}
export function approvalForCriterion(policy, sc) {
  return policy?.mode === 'automatic' || (policy?.mode === 'custom' && !policy.review_scs?.includes(sc)) ? 'automatic' : 'review'
}
export function criterionCapabilityDescription(sc, formats, capability) {
  const labels = {auto: 'Supported automatic repair', assisted: 'Supported proposal when a valid target is available', human: 'Document edit or unsupported target may need you'}
  return formats.map(format => ({format, label: labels[capability?.[format]?.[sc]] || labels.human}))
}

export const POLICY_PREVIEW_VERSION = 'remediation-automation-policy-preview.v1'

export const ROUTING_REASON_COPY = {
  confidence_below_threshold: ['Confidence below threshold', 'The proposal does not clear this policy setting.'],
  subjective_decision: ['Subjective decision', 'A person must judge meaning, intent, or context.'],
  missing_evidence: ['Missing evidence', 'ACP does not have enough evidence to apply the change safely.'],
  unsupported_remediation: ['Unsupported remediation', 'ACP can find this issue but cannot yet apply its fix.'],
  safety_rule: ['Safety rule', 'A policy guardrail always keeps this decision with a person.'],
  failed_verification: ['Failed verification', 'The proposed change did not pass the post-fix check.'],
}

const nonNegativeInteger = (value) => Number.isInteger(value) && value >= 0

export function policyPreviewIntegrity(preview) {
  if (!preview || preview.contract_version !== POLICY_PREVIEW_VERSION) return { valid: false, reason: 'contract_version' }
  const open = preview.open?.findings
  const laneSum = ['automatic', 'review', 'protected']
    .reduce((sum, lane) => sum + (preview.lanes?.[lane]?.findings ?? NaN), 0)
  if (!nonNegativeInteger(open) || !nonNegativeInteger(laneSum) || open !== laneSum) return { valid: false, reason: 'open_lane_sum' }
  if (preview.integrity?.open_equals_lane_sum !== true || preview.integrity?.reason_is_mutually_exclusive !== true) return { valid: false, reason: 'backend_integrity' }
  return { valid: true, reason: null }
}

export const countLabel = ({ findings = 0, files = 0 } = {}) =>
  `${findings} ${findings === 1 ? 'finding' : 'findings'} across ${files} ${files === 1 ? 'file' : 'files'}`

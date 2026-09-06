import { confidenceForFinding, methodForSc } from './confidence.js'
import { proposalMeta } from './reviewCard.js'
import { scOf } from './fixSummary.js'

export const AUTOMATION_LEVELS = [
  { value: 1, name: 'Strict', description: 'Verified deterministic fixes only' },
  { value: 2, name: 'Cautious', description: 'Deterministic fixes with complete evidence' },
  { value: 3, name: 'Balanced', description: 'Adds validated, non-subjective proposals' },
  { value: 4, name: 'Assisted', description: 'Adds supported AI proposals' },
  { value: 5, name: 'Maximum', description: 'Adds lower-confidence eligible proposals' },
]

export const DEFAULT_AUTOMATION_LEVEL = 3

const requiredLevel = (finding) => {
  const sc = scOf(finding?.rule_id || finding?.ruleId)
  const proposal = proposalMeta(finding)
  const method = methodForSc(sc)

  // These are product safety boundaries, not user preferences. Moving the slider never
  // makes subjective, unsupported, or human-only work eligible for unattended changes.
  if (finding?.rejectedFix || method === 'human' || sc === '1.3.3' || proposal?.subjective || !finding?.hasProposal) {
    return null
  }
  const confidence = confidenceForFinding({
    sc,
    proposal: proposal && { validated: proposal.validated, subjective: proposal.subjective },
  })
  if (method === 'deterministic' && confidence.level.key === 'high') return 1
  if (method === 'deterministic') return 2
  if (proposal?.validated) return 3
  if (confidence.level.key === 'medium') return 4
  return 5
}

export function automationForecast(findings = [], level = DEFAULT_AUTOMATION_LEVEL) {
  const rows = Array.isArray(findings) ? findings : []
  let candidates = 0
  let protectedCount = 0
  rows.forEach((finding) => {
    const threshold = requiredLevel(finding)
    if (threshold == null) protectedCount += 1
    else if (threshold <= level) candidates += 1
  })
  return {
    total: rows.length,
    candidates,
    protected: protectedCount,
    review: rows.length - candidates,
  }
}

export function automationLevel(value) {
  return AUTOMATION_LEVELS.find((level) => level.value === Number(value)) || AUTOMATION_LEVELS[DEFAULT_AUTOMATION_LEVEL - 1]
}

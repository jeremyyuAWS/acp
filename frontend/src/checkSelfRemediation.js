import { scOf } from './fixSummary.js'

// A completed transport/job is not a criterion result. Even a successful saved
// assessment does not approve a semantic or manually authored change.
export async function checkSelfRemediation(item, verifySaved) {
  try {
    const evidence = await verifySaved(item)
    if (evidence?.assessment_ok !== true || !Array.isArray(evidence.remaining_criteria)) return {
      status: 'error', verificationMessage: evidence?.reason || 'Saved-copy assessment is incomplete. This finding remains unresolved.',
    }
    const criterion = scOf(item.ruleId || item.rule_id || item.rule)
    const stillPresent = criterion && evidence.remaining_criteria.some(rule => scOf(rule) === criterion)
    return { status: 'checked', verificationMessage: stillPresent
      ? `Saved-copy assessment still reports WCAG ${criterion}. Continue editing or review the remaining finding.`
      : 'Saved-copy assessment recorded. Review its evidence and make the required decision; this check does not approve the manual change.' }
  } catch (error) {
    return { status: 'error', verificationMessage: error?.message || 'Saved-copy verification failed. This finding remains unresolved.' }
  }
}

export function savedCopyVerificationStatus(file = {}, result = {}) {
  const evidence = result?.corrected_copy_assessment
  const current = !!file.remediated_at && !!file.corrected_sha256
    && evidence?.artifact_sha256 === file.corrected_sha256 && evidence.remediated_at === file.remediated_at
  if (current) {
    if (evidence.assessment_ok !== true || evidence.assessment_status !== 'analysed') return { key:'failed', label:'Verification failed', reason:evidence.reason || 'The saved copy could not be fully checked. Retry verification.' }
    if (evidence.remaining_criteria?.length || evidence.remaining_issues?.length) return { key:'remaining', label:'Checked; findings remain', reason:`Remaining criteria: ${(evidence.remaining_criteria || []).join(', ') || 'See the remaining-work checklist'}.` }
    if (Number(evidence.skipped_rules) > 0) return { key:'unconfirmed', label:'Checks incomplete', reason:`${evidence.skipped_rules} selected checks could not run. See the remaining-work checklist.` }
    if (Array.isArray(evidence.remaining_issues) && Array.isArray(evidence.remaining_criteria)) return { key:'passed', label:'Selected checks passed', reason:'The current saved copy passed the recorded checks.' }
  }
  if (file.remediated_at && (file.compliant === true || file.compliant === 1)) return { key:'passed', label:'Selected checks passed', reason:'Recorded selected-scope checks passed.' }
  return { key:'unconfirmed', label:'Awaiting verification', reason:'No current saved-copy check is available. See the remaining-work checklist.' }
}

import { scOf } from './fixSummary.js'
import { documentRows } from './assessMetrics.js'

export const REMEDIATION_CATEGORIES = [
  ['automatic', 'Fully automated'],
  ['approval', 'Fix available — approval needed'],
  ['suggestion', 'AI suggestion needed'],
  ['manual', 'Manual fix required'],
  ['unsupported', 'Cannot fix with ACP'],
  ['blocked', 'Blocked'],
  ['applied', 'Applied — verification pending'],
  ['verified', 'Fixed and verified'],
]
export const categoryLabel = key => REMEDIATION_CATEGORIES.find(([id]) => id === key)?.[1] || 'Blocked'
export const countOf = row => Number.isSafeInteger(row.finding_count) && row.finding_count >= 0 ? row.finding_count : 1
export const typeOf = name => String(name || '').split('.').pop()?.toUpperCase() || 'Unknown'

export function remediationCategory(row) {
  const status = row.disposition || row.status
  if (row.verified === true || status === 'resolved_verified') return 'verified'
  if (row.applied || row.autoApplied) return 'applied'
  if (row.processing_blocked || row.lane === 'blocked' || status === 'blocked') return 'blocked'
  if (row.rejected || row.human_only || row.subjective || ['accessibility_judgment', 'failed_or_rejected_fix', 'ai_disabled'].includes(row.primary_reason)) return 'manual'
  if (row.remediation_supported === false || row.unsupported === true) return 'unsupported'
  if (row.lane === 'automatic') return 'automatic'
  if (row.has_proposal || row.hasProposal || ['approval_required', 'proposal_approval', 'shared_criterion_requires_review'].includes(row.primary_reason)) return 'approval'
  if (row.primary_reason === 'draft_required') return 'suggestion'
  if (row.lane === 'manual' || row.fixMode === 'human') return 'manual'
  if (row.fixMode === 'auto') return 'automatic'
  if (['assisted', 'ai-assisted'].includes(row.fixMode)) return 'suggestion'
  return 'blocked'
}

export function assessmentCategoryRows(files, options) {
  return (documentRows(files, options) || []).flatMap(file => (file.findings || []).map(finding => ({
    ...finding, file: file.file, criterion: finding.sc, finding_count: 1,
    category: remediationCategory(finding),
  })))
}

// A difference in totals alone cannot identify individual findings. Compare like
// file/SC groups and report any unreconciled remainder instead of guessing locations.
export function outsidePlanRows(assessmentRows, forecastRows, scopeFiles) {
  if (!Array.isArray(forecastRows)) return null
  const planned = new Map()
  for (const row of forecastRows) {
    const key = JSON.stringify([row.file, scOf(row.criterion || row.rule_id)])
    planned.set(key, (planned.get(key) || 0) + countOf(row))
  }
  const groups = new Map()
  for (const row of assessmentRows) {
    const sc = scOf(row.criterion || row.rule_id || row.wcag)
    const key = JSON.stringify([row.file, sc])
    if (!groups.has(key)) groups.set(key, { file: row.file, criterion: sc, finding_count: 0 })
    groups.get(key).finding_count += countOf(row)
  }
  return [...groups.entries()].flatMap(([key, row]) => {
    const difference = row.finding_count - (planned.get(key) || 0)
    return difference > 0 ? [{ ...row, finding_count: difference, category: 'outside',
      reason: Array.isArray(scopeFiles) && !scopeFiles.includes(row.file) ? 'Document is outside the selected plan scope.'
        : 'Fewer current plan findings than assessment findings for this file and SC. Changed results or scope may explain the difference; this does not prove a fix.' }] : []
  })
}

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
  // Distinct from plain "applied": this change is not only unverified, its origin is KNOWN to be
  // AI — durable evidence the row carries explicitly (see remediationCategory below), never
  // guessed from a description. A row applied by a rule, or one whose origin nobody recorded,
  // stays 'applied' — this category exists so a reader can tell "we don't know how this was
  // fixed" apart from "an AI wrote this and nobody has checked it yet", which the row above alone
  // cannot say.
  ['ai_applied', 'AI applied · not verified'],
  ['verified', 'Fixed and verified'],
]
export const categoryLabel = key => REMEDIATION_CATEGORIES.find(([id]) => id === key)?.[1] || 'Blocked'
export const countOf = row => Number.isSafeInteger(row.finding_count) && row.finding_count >= 0 ? row.finding_count : 1
export const typeOf = name => String(name || '').split('.').pop()?.toUpperCase() || 'Unknown'

export function remediationCategory(row) {
  const status = row.disposition || row.status
  if (row.verified === true || status === 'resolved_verified') return 'verified'
  // Deliberately still 'applied', not 'ai_applied', here — this is the finding-ACCOUNTING bucket,
  // and keeping AI-evidenced-but-unverified findings inside the existing 'applied' total is what
  // this repo's own aiAppliedUnverified() work (main) already committed to ("keep pending
  // accounting unchanged"), with a test asserting exactly that. 'ai_applied' is a RENDERING-only
  // distinction — see the inline pill in RemediationInbox.jsx and changeCategory() below — layered
  // on top of this bucket rather than replacing it, so no total anywhere has to be re-reconciled.
  if (row.applied || row.autoApplied || aiAppliedUnverified(row)) return 'applied'
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

// The category for an applied CHANGE record (before/after evidence), as opposed to an assessment
// FINDING — a distinct grain `remediationCategory` above does not cover. Same three-way split:
// verified wins outright; otherwise an AI origin the record explicitly carries gets the distinct
// tag; anything else — including a rule-based change or one with no recorded origin — is the
// generic "applied" state. `aiApplied` must be durable evidence (e.g. a recorded model_call_id
// upstream), never inferred from `change.reason`/`change.detail` text.
export const changeCategory = change =>
  change.verified === true ? 'verified' : change.aiApplied === true ? 'ai_applied' : 'applied'

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

// An AI capability or a proposed value alone is not evidence of an application.
export function aiAppliedUnverified(row) {
  const record = row._raw || row
  if (row.verified === true || record.verified === true || [row.disposition, row.status, record.disposition, record.status].includes('resolved_verified')) return false
  if (row.aiApplicationRecord === true) return true
  return record.applied === true && Array.isArray(record.proposals) && record.proposals.some(p => p.model_call_id && p.model)
}

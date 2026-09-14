import { exclusionReason } from './batchReviewSelection.js'
import { requiresPdfSourceEditing } from './pdfStructuralProposal.js'

// Use persisted eligibility and actual proposal lineage. Consent alone is not
// evidence that an automatic job exists, and a document retry rewrites fixes.
export function remediationRecoveryGuidance(row, decisions = {}) {
  if (!row || row.validated || row.automaticQueued) return null
  if (requiresPdfSourceEditing(row)) return {
    title: 'Edit the source document',
    reason: 'ACP cannot write this PDF heading or table structure from a prose suggestion.',
    next: 'Add the structure in the original document or a PDF accessibility editor, then assess the updated copy.',
  }
  const marker = row.automaticDisposition
  if (row.applied && !row.validated || ['verification_failed', 'verification_pending'].includes(row.status)) return {
    title: 'Check the saved correction',
    reason: marker?.reason || 'The recorded correction has not passed independent verification.',
    next: 'Check the saved result and failed criterion. A document retry reapplies fixes; it is not a verification-only retry.',
    plan: true,
  }
  const exclusion = exclusionReason(row, decisions)
  if (exclusion === 'Missing proposal' || exclusion?.includes('refresh') || exclusion === 'Version unavailable — review individually') return {
    title: exclusion === 'Missing proposal' ? 'A complete suggestion is needed' : 'Refresh the suggestion',
    reason: exclusion === 'Missing proposal' ? 'One or more findings do not have a usable proposed value.'
      : exclusion === 'Version unavailable — review individually' ? 'The suggestion does not have the saved version information required for automatic approval.'
      : 'The suggestion or its source version is stale or invalid.',
    next: 'Open the remediation plan to check generation and refresh options. The current item remains unresolved.',
    plan: true,
  }
  if (marker?.responsibility === 'human') return {
    title: 'Your decision is needed',
    reason: marker.reason || 'The saved policy requires individual review of this change.',
    next: 'Review the proposed value, edit it if needed, then apply it or send it for manual work.',
  }
  if (row.automaticReason) return {
    title: 'Automatic application is not confirmed',
    reason: row.automaticReason,
    next: 'Check the remediation plan for eligibility and generation status. No automatic job is claimed for this item.',
    plan: true,
  }
  return null
}

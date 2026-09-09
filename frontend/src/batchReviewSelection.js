import { isResolved, laneOf } from './remediationInboxModel.js'

export function proposalValues(f) {
  const proposals = f.proposals || f._raw?.proposals || []
  return proposals.length ? proposals.map(p => p.proposed_value) : [f.after]
}
export function exclusionReason(f, decisions = {}, drafts = {}) {
  if (isResolved(f, decisions)) return 'Already reviewed'
  if (f.stale || f.superseded || f._raw?.superseded) return 'Stale — refresh and review'
  const lane = laneOf(f).key
  if (lane === 'review') return 'Already applied — review individually'
  if (lane === 'manual' || lane === 'handoff') return 'Manual work'
  if (lane !== 'apply' || f.canApprove === false) return 'Blocked or unavailable'
  if (drafts[f.id] != null && drafts[f.id] !== f.after) return 'Unsaved edit — review individually'
  if (!proposalValues(f).every(v => typeof v === 'string' && v.trim())) return 'Missing proposal'
  // Production rows require persisted lineage; legacy/demo rows may be inspected individually.
  if (!f._raw?.proposal_snapshot_ids?.length || f._raw.proposal_snapshot_ids.length !== proposalValues(f).length
    || f._raw.proposal_snapshot_ids.some(id => !id) || f._raw?.source_revision == null || f._raw?.decision_version == null)
    return 'Version unavailable — review individually'
  return null
}
// Deliberately include every proposal and locator, not just the first displayed value.
export function selectionFingerprint(f) {
  return JSON.stringify([f.id, f.scanId, f.file, f.ruleId || f.rule_id,
    f.before, f.after, f.proposals || f._raw?.proposals,
    f._raw?.decision_version, f._raw?.proposal_snapshot_ids, f._raw?.source_revision])
}
export function snapshotFinding(f) {
  return { finding: JSON.parse(JSON.stringify(f)), fingerprint: selectionFingerprint(f),
    requestId: globalThis.crypto?.randomUUID?.() || `batch-${Date.now()}-${Math.random().toString(16).slice(2)}` }
}
export function selectionProblem(entry, visible, decisions, drafts) {
  const current = visible.find(f => f.id === entry.finding.id)
  if (!current) return 'Outside this view or no longer available'
  return exclusionReason(current, decisions, drafts)
    || (selectionFingerprint(current) !== entry.fingerprint ? 'Proposal or source changed — select again' : null)
}
export function batchDecision(entry) {
  const f = entry.finding
  return { state: 'accepted', value: proposalValues(f)[0], approvedValues: proposalValues(f),
    requestId: entry.requestId, expectedVersion: f._raw.decision_version,
    expectedProposalSnapshotIds: [...f._raw.proposal_snapshot_ids], expectedSourceRevision: f._raw.source_revision,
    selectionFingerprint: entry.fingerprint }
}

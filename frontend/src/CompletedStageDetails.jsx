import DiscoverRunProgress from './DiscoverRunProgress.jsx'
import AssessRunProgress from './AssessRunProgress.jsx'

const value = (input) => typeof input === 'number' && Number.isFinite(input) ? input : 0

/** Rehydrate the designed live Discovery card from its canonical SSE projection after a reload.
 * The direct discovery stream carries more detail when it is available; this keeps the same
 * checklist, heartbeat and delta counters when only the durable stage stream has reconnected. */
export function liveDiscoverProgress(snapshot) {
  const domain = snapshot?.domain_reconciliation || {}
  const buckets = domain.buckets || {}
  const work = snapshot?.counts?.work_items || {}
  const filesFound = value(domain.accounted ?? domain.partitioned ?? domain.total)
  return {
    phase: snapshot?.state === 'queued' ? 'queued' : 'discovering',
    files_found: filesFound,
    files_evaluated: value(buckets.evaluated),
    folders_found: typeof buckets.folders_visited === 'number' ? buckets.folders_visited : null,
    folders_visited: typeof buckets.folders_visited === 'number' ? buckets.folders_visited : null,
    save_new: typeof buckets.saved === 'number' ? buckets.saved : null,
    save_updated: 0,
    current: work.current || snapshot?.current_item || null,
    run_id: snapshot?.execution_id || snapshot?.workflow_id || 'discover',
    updated_at: snapshot?.last_durable_update_at || snapshot?.generated_at || null,
  }
}

/** Translate a durable final snapshot into the public props of the stage card that owned it live. */
export function completedDiscoverProgress(snapshot) {
  const domain = snapshot?.domain_reconciliation || {}
  const buckets = domain.buckets || {}
  const total = value(domain.total)
  return {
    phase: 'done', files_found: total, files_evaluated: total,
    lifecycle_matches: Object.entries(buckets).reduce((sum, [key, count]) =>
      /archive|delete|tag/i.test(key) ? sum + value(count) : sum, 0),
    lifecycle_archive: value(buckets.archive_candidate ?? buckets['Archive Candidate']),
    lifecycle_delete: value(buckets.delete_candidate ?? buckets['Delete Candidate']),
    lifecycle_tagged: value(buckets.tagged),
    lifecycle_unevaluable: value(buckets.unevaluable),
    updated_at: snapshot?.last_durable_update_at || snapshot?.generated_at || null,
  }
}

export function completedAssessSnapshot(snapshot) {
  const audit = snapshot?.assessment_summary
  const findings = audit?.findings_recorded
  const hasFindings = audit?.valid !== false && typeof findings === 'number' && Number.isFinite(findings) && findings >= 0
  const domain = audit?.domain_reconciliation || snapshot?.domain_reconciliation || {}
  const buckets = domain.buckets || {}
  const total = value(domain.total)
  return {
    available: true, active: false, phase: 'done',
    totals: { discovered: total, eligible: total },
    kpis: { completed: value(buckets.assessed), processing: 0,
      ...(hasFindings ? { findings_so_far: findings } : {}) },
    kpis_pending: [...(hasFindings ? [] : ['findings_so_far']), 'need_attention', 'unable_to_assess'],
    source: snapshot?.source || null, scope: snapshot?.scope || null,
    ai_activity: snapshot?.ai_activity || null,
    _live: { measuredAt: snapshot?.last_durable_update_at || snapshot?.generated_at || null,
      mode: 'complete' },
  }
}

export default function CompletedStageDetails({ snapshot }) {
  if (snapshot?.stage === 'discover') {
    return <DiscoverRunProgress progress={completedDiscoverProgress(snapshot)} busy={false}
      source={snapshot?.source || null} scope={snapshot?.scope || null} />
  }
  if (snapshot?.stage === 'assess') {
    return <AssessRunProgress snapshot={completedAssessSnapshot(snapshot)} />
  }
  return null
}

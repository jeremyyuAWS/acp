import DiscoverRunProgress from './DiscoverRunProgress.jsx'
import AssessRunProgress from './AssessRunProgress.jsx'

const value = (input) => typeof input === 'number' && Number.isFinite(input) ? input : 0

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
  const domain = snapshot?.domain_reconciliation || {}
  const buckets = domain.buckets || {}
  const total = value(domain.total)
  return {
    available: true, active: false, phase: 'done',
    totals: { discovered: total, eligible: total },
    kpis: { completed: value(buckets.assessed), processing: 0 },
    source: snapshot?.source || null, scope: snapshot?.scope || null,
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

import { releaseBatchDomain, releaseBatchProgress } from './releaseBatchProgress.js'
import { findingMath, originalFindingMetrics } from './RemediationAssessmentProgress.jsx'

const count = value => Number.isSafeInteger(value) && value >= 0
const digest = value => /^[a-f0-9]{64}$/i.test(value || '')
export function savedDestinationLinks(folders = []) {
  const seen = new Set()
  return folders.flatMap(folder => {
    try {
      const url = new URL(folder?.url)
      if (url.protocol !== 'https:' || url.username || url.password || seen.has(url.href)) return []
      seen.add(url.href)
      return [{ url: url.href, name: folder.name || 'published folder' }]
    } catch { return [] }
  })
}

// Scope totals come from the saved authorization, never the most recent one-file request.
// A published bucket alone cannot confirm the currently displayed corrected bytes.
export function releaseOutcomeSummary({ scanId, authorization, pending = false, error, files = [], results = {}, snapshot } = {}) {
  const batch = releaseBatchProgress({ stage: 'release', release_batch_progress: authorization?.batch_progress })
  const domain = releaseBatchDomain(batch)
  const names = authorization?.files
  const membership = batch?.file_membership
  const scoped = !!domain && !!authorization?.id && batch.authorization_id === authorization.id
    && batch.run_id === authorization.run_id && Array.isArray(names) && names.length === domain.total
    && new Set(names).size === names.length && names.every(name => Object.hasOwn(membership, name))
    && names.every(name => files.filter(file => file.file === name).length === 1)
  const available = !pending && !error && scoped
  const currentReceipt = file => digest(file.corrected_sha256)
    && results[file.file]?.status === 'published'
    && results[file.file]?.artifact_digest === `sha256:${file.corrected_sha256}`
  const delivered = available ? names.filter(name => membership[name] === 'published'
    && currentReceipt(files.find(file => file.file === name))).length : null
  const confirmed = available && delivered === batch.delivered
  const complete = confirmed && batch.state === 'succeeded' && delivered === domain.total
  const blocked = available && (batch.state === 'failed' || domain.buckets.failed > 0 || domain.buckets.skipped > 0)
  const original = snapshot?.finding_reconciliation?.original_assessment
  const originalMatches = available && Array.isArray(original)
    && !!originalFindingMetrics(original, snapshot.finding_reconciliation.assessed)
    && original.every(group => names.includes(group.file))
  const findingBound = originalMatches && snapshot.total_documents === names.length
    && (snapshot.scan_id || snapshot.run_id) === scanId
    && !!snapshot.batch_id && snapshot.batch_id === authorization.run_id
  const findings = findingBound ? findingMath(snapshot) : { exact: false }
  const open = findings.exact ? ['awaiting_review', 'approved_pending_verification', 'unchanged_no_fix', 'failed']
    .reduce((sum, key) => sum + findings.rec[key], 0) : null
  return {
    state: complete ? 'complete' : blocked ? 'attention' : available && confirmed ? 'processing' : 'unavailable',
    title: complete ? 'Delivery complete' : blocked ? 'Delivery needs attention'
      : available && confirmed ? 'Delivery in progress' : 'Checking delivery confirmation',
    total: available ? domain.total : null,
    delivered: confirmed ? delivered : null,
    remainingCopies: confirmed ? domain.total - delivered : null,
    fixed: findings.exact && count(findings.fixed) ? findings.fixed : null,
    open,
    excluded: findings.exact ? findings.rec.excluded : null,
    superseded: findings.exact ? findings.rec.superseded : null,
    complete,
  }
}

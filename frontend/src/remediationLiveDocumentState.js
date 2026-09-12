import { scOf } from './fixSummary.js'
import { releaseReadiness, releaseSourceState, hasSavedCorrectedCopy } from './releaseClarityModel.js'
import { remediationCategory, aiAppliedUnverified } from './remediationCategories.js'

export function materialKey(scanId, snapshot, events = []) {
  const relevant = events.filter(e => (!e.scan_id || e.scan_id === scanId) && /applied|verified|review|completed|failed|proposal|disposition|stored|delivered/.test(e.kind || e.action || ''))
  const eventKeys = relevant.map(event => String(event.id || event.event_id || event.occurred_at || event.key || event.kind)).sort()
  return JSON.stringify([snapshot?.batch_id, snapshot?.state, snapshot?.documents, snapshot?.findings,
    snapshot?.finding_accounting, snapshot?.finding_reconciliation, snapshot?.fixes, snapshot?.delivery, snapshot?.review, snapshot?.file_processing, eventKeys])
}

export function liveDocumentCounts(documents, ledger, review = [], batchId) {
  if (!ledger?.available || !Array.isArray(ledger.items) || (batchId && ledger.batch_id !== batchId)) return null
  const identityCounts = ledger.items.reduce((counts, finding) => counts.set(finding.finding_id, (counts.get(finding.finding_id) || 0) + 1), new Map())
  const result = []
  for (const doc of documents) {
    const findings = ledger.items.filter(f => f.file === doc.file)
    const identities = new Set()
    const invalidIdentity = findings.some(finding => !finding.finding_id || identityCounts.get(finding.finding_id) > 1 || identities.has(finding.finding_id) || !identities.add(finding.finding_id))
    const groupCounts = rows => rows.reduce((counts, row) => { const sc = scOf(row.sc || row.rule_id); counts[sc] = (counts[sc] || 0) + 1; return counts }, {})
    const assessedGroups = groupCounts(doc.findings || [])
    const recordedGroups = groupCounts(findings)
    const sameGroups = Object.keys({...assessedGroups, ...recordedGroups}).every(sc => assessedGroups[sc] === recordedGroups[sc])
    if (invalidIdentity || findings.length !== doc.totalFindings || !sameGroups) {
      result.push({ ...doc, liveCounts: null, reconciliation: { expected: doc.totalFindings ?? null, recorded: findings.length, reason: invalidIdentity ? 'Finding identities are missing or duplicated.' : !sameGroups && findings.length === doc.totalFindings ? 'Recorded criteria differ from this assessment.' : 'Recorded finding population differs from this assessment.' } })
      continue
    }
    const counts = {}
    for (const finding of findings) {
      const item = review.find(r => r.id === finding.review_item_id && r.file === doc.file)
      let category
      if (finding.disposition === 'resolved_verified') category = 'verified'
      else if (finding.disposition === 'remediation_failed') category = 'blocked'
      else if (finding.disposition === 'excluded_by_policy') category = 'excluded'
      else if (finding.disposition === 'superseded_by_reassessment') category = 'superseded'
      else if (finding.disposition === 'unchanged_no_fix') category = 'manual'
      else if (item?.applied === true || item?.applied === 1) category = aiAppliedUnverified({ ...item, applied:true }) ? 'ai_applied' : 'applied'
      else if (finding.disposition === 'approved_pending_verification') category = 'approved'
      else if (item?.proposals?.length) category = 'approval'
      else {
        const sameSC = doc.findings.filter(r => r.sc === scOf(finding.rule_id))
        const categories = new Set(sameSC.map(remediationCategory))
        category = categories.size === 1 && ['manual', 'unsupported', 'blocked'].includes([...categories][0]) ? [...categories][0] : 'remaining'
      }
      counts[category] = (counts[category] || 0) + 1
    }
    result.push({ ...doc, liveCounts: counts })
  }
  return result
}

export function findingOutcomeTotals(documents = []) {
  return documents.reduce((totals, document) => {
    for (const [category, count] of Object.entries(document.liveCounts || {})) totals[category] = (totals[category] || 0) + count
    return totals
  }, {})
}

// Document progress does not require an exact per-finding ledger. Use each
// independent recorded fact without turning individual repair records into
// whole-document verification.
export function recordedDocumentProgress(row, file, { confirmed, release, source, review = [], snapshot } = {}) {
  if (snapshot?.active_attempts?.some(attempt => attempt.file === row.file && attempt.lease_valid === true)) return 'processing'
  const releaseProgress = file && confirmedReleaseProgress(file, release, source, review)
  if (releaseProgress) return releaseProgress
  const counts = confirmed?.liveCounts
  if (counts) {
    if (['approved', 'applied', 'ai_applied'].some(key => counts[key] > 0)) return 'processing'
    return counts.verified === row.totalFindings && row.totalFindings > 0 ? 'verified' : 'attention'
  }
  if (review.some(item => item.file === row.file && item.status === 'pending')) return 'attention'
  if (hasSavedCorrectedCopy(file || {}) && (file.compliant === true || file.compliant === 1)) return 'verified'
  if (row.opened === false || ['attention', 'awaiting_review'].includes(row.state)) return 'attention'
  return undefined
}

export function releaseProgressState(state) {
  return ({ ready: 'ready', released: 'published', delivering: 'processing', applying: 'processing' })[state?.status] || 'attention'
}

export function confirmedReleaseProgress(file, release, source, review = []) {
  if (!release || !Array.isArray(release.documents) || !source || !Array.isArray(source.files) || !hasSavedCorrectedCopy(file)) return undefined
  const receipt = release.documents.find(row => row.file === file.file)
  // Only a receipt for this corrected artifact can establish publication here.
  const currentReceipt = receipt?.status === 'published' && receipt.artifact_digest === `sha256:${file.corrected_sha256}`
    ? receipt : receipt?.status === 'published' ? undefined : receipt
  const sourceByFile = Object.fromEntries(source.files.map(row => [row.file, row]))
  const pending = review.filter(item => item.file === file.file && item.status === 'pending').length
  const state = releaseReadiness({ ...file, published_at: null }, {
    results: currentReceipt ? { [file.file]: currentReceipt } : {},
    sourceState: row => releaseSourceState(sourceByFile[row.file]), pending: { [file.file]: pending },
  })
  return releaseProgressState(state)
}

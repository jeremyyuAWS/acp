import { releaseReadiness, releaseSourceState, hasSavedCorrectedCopy } from './releaseClarityModel.js'
import { remediationCategory, aiAppliedUnverified } from './remediationCategories.js'

export function materialKey(scanId, snapshot, events = []) {
  const relevant = events.filter(e => (!e.scan_id || e.scan_id === scanId) && /applied|verified|review|completed|failed|proposal|disposition|stored|delivered/.test(e.kind || e.action || ''))
  const last = relevant.at(-1)
  return JSON.stringify([snapshot?.batch_id, snapshot?.state, snapshot?.documents, snapshot?.findings,
    snapshot?.finding_accounting, snapshot?.review, last?.id || last?.event_id || last?.occurred_at])
}

export function liveDocumentCounts(documents, ledger, review = [], batchId) {
  if (!ledger?.available || !Array.isArray(ledger.items) || (batchId && ledger.batch_id !== batchId)) return null
  const ids = new Set()
  if (ledger.items.some(r => !r.finding_id || ids.has(r.finding_id) || !ids.add(r.finding_id))) return null
  const result = []
  for (const doc of documents) {
    const findings = ledger.items.filter(f => f.file === doc.file)
    if (findings.length !== doc.totalFindings) return null
    const counts = {}
    for (const finding of findings) {
      const item = review.find(r => r.id === finding.review_item_id && r.file === doc.file)
      let category
      if (finding.disposition === 'resolved_verified') category = 'verified'
      else if (item?.applied === true || item?.applied === 1) category = aiAppliedUnverified({ ...item, applied:true }) ? 'ai_applied' : 'applied'
      else if (finding.disposition === 'remediation_failed') category = 'blocked'
      else if (finding.disposition === 'excluded_by_policy') category = 'excluded'
      else if (finding.disposition === 'superseded_by_reassessment') category = 'superseded'
      else if (finding.disposition === 'unchanged_no_fix') category = 'manual'
      else if (finding.disposition === 'approved_pending_verification') category = 'approved'
      else if (item?.proposals?.length) category = 'approval'
      else {
        const sameSC = doc.findings.filter(r => r.sc === finding.rule_id)
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

export function releaseProgressState(state) {
  return ({ ready: 'ready', released: 'published', delivering: 'processing' })[state?.status] || 'attention'
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

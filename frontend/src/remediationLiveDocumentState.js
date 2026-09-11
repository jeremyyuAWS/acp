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
        category = categories.size === 1 ? [...categories][0] : 'remaining'
      }
      counts[category] = (counts[category] || 0) + 1
    }
    result.push({ ...doc, liveCounts: counts })
  }
  return result
}

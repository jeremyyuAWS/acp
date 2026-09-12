const KINDS = new Set(['pdf-tag-heading', 'pdf-table-header-scope'])
export const isPdfStructuralProposal = proposal => KINDS.has(proposal?.kind)
export const proposalsFor = finding => finding?.proposals || finding?._raw?.proposals || []
export const isPdfStructuralRow = finding => {
  const proposals = proposalsFor(finding)
  return proposals.length > 0 && proposals.every(isPdfStructuralProposal)
}
// Display only. Approval always carries untouched server JSON and immutable lineage.
export function pdfStructuralSummary(proposal) {
  if (!isPdfStructuralProposal(proposal) || !String(proposal.locator || '').startsWith('pdf:struct:')) return null
  let plan
  try { plan = JSON.parse(proposal.proposed_value) } catch { return null }
  if (!plan || typeof plan !== 'object' || Array.isArray(plan) || Object.keys(plan).length !== 2) return null
  const subject = typeof proposal.subject_text === 'string' ? proposal.subject_text.trim().slice(0, 120) : ''
  if (proposal.kind === 'pdf-tag-heading' && plan.op === 'heading' && /^H[1-6]$/.test(plan.role)) {
    return `Mark ${subject ? `“${subject}”` : 'existing tagged text'} as Heading ${plan.role.slice(1)}`
  }
  if (proposal.kind === 'pdf-table-header-scope' && plan.op === 'header-scope' && ['Row', 'Column', 'Both'].includes(plan.scope)) {
    return `Associate ${subject ? `“${subject}”` : 'this existing table header'} with ${plan.scope === 'Both' ? 'its row and column' : `its ${plan.scope.toLowerCase()}`}`
  }
  return null
}

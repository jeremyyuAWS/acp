import { REMEDIATION_CATEGORIES, categoryLabel } from './remediationCategories.js'
import './remediation-category-pills.css'
export const CATEGORY_SHORT_LABELS = { automatic: 'Auto', approval: 'Approve', suggestion: 'AI', manual: 'Manual', unsupported: 'No ACP', blocked: 'Blocked', applied: 'Pending', ai_applied: 'AI applied', verified: 'Verified' }
const EXPLANATIONS = {
  automatic: 'ACP has a supported rule-based fix that can run under your remediation plan without an AI suggestion or individual approval. It is counted as verified only after the fix passes its checks.',
  approval: 'A proposed fix is available, but approval is required before ACP applies it. Applying the proposal saves the change and starts verification.',
  suggestion: 'An AI-generated suggestion is needed for this finding. Your remediation plan determines whether a usable suggestion is applied automatically or sent for review.',
  manual: 'This finding needs a person to make or review the correction in the document. ACP cannot complete the fix automatically.',
  unsupported: 'ACP can report this finding but does not currently provide a supported correction for it. The remaining-work checklist keeps it visible for follow-up.',
  blocked: 'Remediation cannot proceed because a required file, permission, source detail, or other prerequisite is unavailable. Resolve the recorded blocker before retrying.',
  applied: 'A change has been applied, but verification has not confirmed the finding is fixed. A saved change alone does not count as a verified fix.',
  ai_applied: 'An AI-generated change has been applied, but it has not yet been independently verified. Review or verification may still identify remaining work.',
  verified: 'Recorded verification checks confirmed that this finding was fixed. This does not certify the entire document or mean every accessibility requirement has passed.',
}
export const categoryExplanation = category => EXPLANATIONS[category] || EXPLANATIONS.blocked
export default function RemediationCategoryPill({ category, count, unit = 'findings', fullLabel = false }) {
  return <span className={`remediation-category-pill remediation-category-pill--${category}`} title={categoryExplanation(category)} aria-label={`${categoryLabel(category)}${count == null ? '' : `: ${count} ${unit}`}`}>
    {fullLabel ? categoryLabel(category) : CATEGORY_SHORT_LABELS[category]}{count != null && <> <strong className="remediation-category-pill__count">{count}</strong>{unit === 'records' && ' records'}</>}
  </span>
}
export function RemediationCategoryLegend() {
  return <details><summary>Category legend</summary><div className="remediation-category-legend" aria-label="Remediation category legend"><strong>Legend</strong>{REMEDIATION_CATEGORIES.map(([key, label]) => <span key={key}><RemediationCategoryPill category={key} /> {label}</span>)}</div></details>
}

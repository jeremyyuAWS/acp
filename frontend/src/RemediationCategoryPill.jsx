import { REMEDIATION_CATEGORIES, categoryLabel } from './remediationCategories.js'
import './remediation-category-pills.css'
const SHORT = { automatic: 'Auto', approval: 'Approve', suggestion: 'AI', manual: 'Manual', unsupported: 'No ACP', blocked: 'Blocked', applied: 'Pending', verified: 'Verified' }
export default function RemediationCategoryPill({ category, count, unit = 'findings', fullLabel = false }) {
  return <span className={`remediation-category-pill remediation-category-pill--${category}`} title={categoryLabel(category)} aria-label={`${categoryLabel(category)}${count == null ? '' : `: ${count} ${unit}`}`}>
    {fullLabel ? categoryLabel(category) : SHORT[category]}{count != null && <> <strong className="remediation-category-pill__count">{count}</strong>{unit === 'records' && ' records'}</>}
  </span>
}
export function RemediationCategoryLegend() {
  return <div className="remediation-category-legend" aria-label="Remediation category legend"><strong>Legend</strong>{REMEDIATION_CATEGORIES.map(([key, label]) => <span key={key}><RemediationCategoryPill category={key} /> {label}</span>)}</div>
}

import './remediation-evidence.css'
import { useEffect, useRef } from 'react'
import { criterionOf } from './wcagFinding.js'
import { REMEDIATION_CATEGORIES, remediationCategory, changeCategory } from './remediationCategories.js'
import RemediationCategoryPill, { RemediationCategoryLegend } from './RemediationCategoryPill.jsx'
import { scOf } from './fixSummary.js'
import './remediation-file-detail.css'
const text = value => value == null ? 'Not recorded' : typeof value === 'string' ? value : JSON.stringify(value, null, 2)
export default function RemediationFileDetail({ row, changes, loading, unavailable, onRetry, onBack, onNext, nextName }) {
  const heading = useRef(null)
  useEffect(() => { heading.current?.focus() }, [row.file])
  const groups = {}
  for (const finding of row.findings) (groups[finding.sc] ||= { findings: [], changes: [] }).findings.push(finding)
  for (const change of changes) (groups[scOf(change.rule_id || change.sc || change.wcag) || 'Not recorded'] ||= { findings: [], changes: [] }).changes.push(change)
  return <section className="remediation-file-page" aria-label="Remediation details by WCAG success criterion">
    <nav><button type="button" onClick={onBack}>← All documents</button>{onNext && <button type="button" onClick={onNext}>Next: {nextName} →</button>}</nav>
    <h2 ref={heading} tabIndex={-1}>{row.file}</h2><p className="muted">{row.fmt?.toUpperCase()} · Remediation results</p>
    <div className="panel remediation-file-summary">
      <div><small>Findings</small><strong>{row.totalFindings}</strong></div>
      <div><small>Remediation categories</small><span>{REMEDIATION_CATEGORIES.map(([category]) => {
        const count = row.findings.filter(finding => remediationCategory(finding) === category).length
        return count > 0 && <RemediationCategoryPill key={category} category={category} count={count} />
      })}</span></div>
      <div><small>Auto-fix available</small><strong>{row.autoFixAvailable}</strong></div>
      <div><small>Needs a person</small><strong>{row.humanReviewRequired}</strong></div>
      <div><small>Coverage for this file</small><span>{row.criteriaEvaluated.length} of {row.selectedChecks} criteria evaluated</span></div>
    </div>
    <RemediationCategoryLegend />
    <h3>Findings and fixes by WCAG success criterion</h3>
    <p className="muted">{row.totalFindings} assessment findings · {changes.length} recorded changes. Change records are separate from findings; applying a change does not establish that the document is accessible.</p>
    {loading && <p role="status">Loading file evidence…</p>}
    {unavailable && <p role="status">No additional file evidence is available. This does not establish that the file has no fixes. <button type="button" onClick={onRetry}>Refresh evidence</button></p>}
    {Object.entries(groups).map(([sc, group]) => {
      const criterion = criterionOf(sc)
      return <article className="remediation-sc-card" key={sc}>
        <header><div>{REMEDIATION_CATEGORIES.map(([category]) => {
          const count = group.findings.filter(finding => remediationCategory(finding) === category).length
          return count > 0 && <RemediationCategoryPill key={category} category={category} count={count} />
        })}</div><div><h4>SC {sc}{criterion ? ` ${criterion.name}` : ''}{criterion?.level && <span className="muted"> · Level {criterion.level}</span>}</h4><p className="muted">{criterion?.req}</p></div><small>{group.findings.length} findings · {group.changes.length} change records</small></header>
        {group.findings.map((finding, index) => <div className="remediation-sc-row" key={`finding-${index}`}><span className="remediation-evidence remediation-evidence--description">{finding.detail || 'Finding recorded'}</span><RemediationCategoryPill fullLabel category={remediationCategory(finding)} /></div>)}
        {group.changes.map((change, index) => <div className="remediation-sc-change" key={change.id || index}>
          <h4>Change {index + 1}{change.page != null ? ` · Page ${change.page}` : ''} <RemediationCategoryPill fullLabel category={changeCategory(change)} /></h4>
          <dl><dt>Before</dt><dd className="remediation-evidence">{text(change.before)}</dd><dt>After</dt><dd className="remediation-evidence">{text(change.after ?? change.value ?? change.approved_value)}</dd></dl>
          <p>Verification: {change.verified === true ? 'Verified' : 'Not reported in this record'}</p>{change.reason && <p>{text(change.reason)}</p>}
        </div>)}
      </article>
    })}
    {!Object.keys(groups).length && <p>No findings or change records are available for this file.</p>}
  </section>
}

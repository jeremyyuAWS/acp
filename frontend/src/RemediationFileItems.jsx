import { useEffect, useRef, useState } from 'react'

const ROUTES = [['manual', 'Manual work'], ['review', 'Proposal review'], ['automatic', 'Automatic fixes'], ['blocked', 'Blocked / unknown']]
const ACTIONS = {
  ai_disabled: 'Edit the source content manually, or return to the plan to enable AI drafting. AI drafts still need approval.',
  accessibility_judgment: 'Review the content and make the required accessibility judgment. Update the source document where needed.',
  failed_or_rejected_fix: 'Inspect the rejected or failed fix and correct the source document before verification.',
  source_editing: 'Make this correction in the source document, then reassess it.',
  approval_required: 'Review and approve the proposed correction before applying it.',
  validation_required: 'Review the correction; qualifying validation evidence is not yet available for automatic application.',
  draft_required: 'Prepare a draft, then have a person review and approve it.',
  proposal_approval: 'Review the AI proposal before applying it.',
}
const count = n => Number.isFinite(n) ? n.toLocaleString() : 'Not reported'

export default function RemediationFileItems({ file, rows, initialLane = 'manual', onBack }) {
  const [lane, setLane] = useState(initialLane)
  const heading = useRef(null)
  useEffect(() => { heading.current?.focus(); heading.current?.scrollIntoView?.({ block: 'start' }) }, [])
  const items = rows.filter(row => row.file === file.file && row.lane === lane)
  const label = ROUTES.find(([key]) => key === lane)[1]
  return <section className="remediation-file-items">
    <button type="button" onClick={onBack}>← Back to files</button>
    <h3 ref={heading} tabIndex={-1}>{file.file}</h3>
    <p>All forecast items for this file. Grouped by accessibility rule; one rule may cover multiple findings.</p>
    <div className="remediation-file-items__routes" role="group" aria-label="Finding category">
      {ROUTES.map(([key, title]) => <button type="button" key={key} aria-pressed={lane === key} onClick={() => setLane(key)}>
        {title} · {count(file[key])}
      </button>)}
    </div>
    <h4>{label} — {count(file[lane])} findings</h4>
    {items.length ? <ol className="remediation-file-items__list">{items.map((row, index) => <li key={row.id || `${row.rule_id}-${index}`}>
      <h4>{row.plain_name || row.rule_name || row.rule_id || row.criterion || 'Accessibility finding'}</h4>
      <p><strong>{count(row.finding_count)} {row.finding_count === 1 ? 'finding' : 'findings'}</strong> · Rule {row.criterion || row.rule_id || 'not reported'}{row.level ? ` · Level ${row.level}` : ''}</p>
      <p><strong>Why:</strong> {typeof row.primary_reason === 'string' ? row.primary_reason.replaceAll('_', ' ') : 'Reason not reported'}.</p>
      <p><strong>Next action:</strong> {ACTIONS[row.primary_reason] || (lane === 'manual' ? 'Edit the source or request an accessibility judgment.' : lane === 'review' ? 'Review the proposal before application.' : lane === 'automatic' ? 'Apply the eligible fix, then verify.' : 'Investigate the blocker before remediation.')}</p>
    </li>)}</ol> : <p>{file[lane] === 0 ? `No ${label.toLowerCase()} findings for this file.` : 'Item details are unavailable for this category; the count above is retained.'}</p>}
    <p className="remediation-impact__note">Individual page, slide, or cell locations are not included in this forecast. Viewing this list does not resolve findings.</p>
  </section>
}

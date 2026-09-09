import { useCallback, useState } from 'react'
import Drawer from './Drawer.jsx'
import './remediation-contribution.css'

const outcomes = [['fixed', 'Verified fixes'], ['awaiting_review', 'Awaiting review'], ['approved', 'Approved, awaiting verification'], ['unresolved', 'Unresolved'], ['processing', 'Processing'], ['unavailable', 'Evidence unavailable']]
const origins = [['rules', 'Rules'], ['first_ai', 'First AI usable proposals'], ['fallback_ai', 'Additional fallback proposals']]
const validCount = n => Number.isSafeInteger(n) && n >= 0
const number = n => validCount(n) ? n.toLocaleString() : 'Unavailable'

export default function RemediationContribution({ snapshot }) {
  const [selection, setSelection] = useState(null)
  const close = useCallback(() => setSelection(null), [])
  const available = snapshot?.contract_version === 'remediation-contribution.v1' && snapshot.coverage !== 'unavailable' && validCount(snapshot.baseline_total)
  const findings = Array.isArray(snapshot?.findings) ? snapshot.findings : []
  const matches = selection ? findings.filter(finding => finding[selection.field] === selection.key) : []
  const total = snapshot?.baseline_total
  const select = (field, key, label) => setSelection({ field, key, label })
  return <section className="remediation-contribution" aria-label="Measured contribution">
    <h4>Measured contribution</h4>
    {!available ? <p>Measured contribution is unavailable. This run does not have a complete link to its original findings; missing evidence is not a zero count.</p> : <>
      <p><strong>{number(total)} original findings</strong> across {number(snapshot.selected_file_count)} selected files. Each finding is counted once in each view, across retries and proposal revisions.</p>
      {snapshot.coverage === 'partial' && <p role="note">Partial coverage: only linked evidence is attributed. Historical records may be unavailable.</p>}
      <p>{snapshot.note || 'Usable proposals are not verified fixes. Approval and successful verification are recorded separately.'}</p>
      <div className="contribution-bars" aria-label="Contribution by source, scaled to original findings">
        {origins.map(([key, label]) => <div className="contribution-bar-row" key={key}>
          <button type="button" onClick={() => select('origin', key, label)}>{label}: {number(snapshot.contributions?.[key])}</button>
          <div className="contribution-track" aria-hidden="true"><span style={{ width: `${validCount(snapshot.contributions?.[key]) && total > 0 ? Math.min(100, 100 * snapshot.contributions[key] / total) : 0}%` }} /></div>
        </div>)}
      </div>
      <p>All source bars use the same {number(total)}-finding baseline. AI review checked {number(snapshot.reviewer?.checked_proposals)} proposals; reviews do not add findings or fixes.</p>
      <table><caption>Contribution counts and matching findings</caption><thead><tr><th scope="col">Source</th><th scope="col">Original findings</th></tr></thead><tbody>
        {origins.map(([key, label]) => <tr key={key}><th scope="row"><button type="button" onClick={() => select('origin', key, label)}>{label}</button></th><td>{number(snapshot.contributions?.[key])}</td></tr>)}
      </tbody></table>
      <table><caption>Current outcomes of original findings</caption><thead><tr><th scope="col">Outcome</th><th scope="col">Original findings</th></tr></thead><tbody>
        {outcomes.map(([key, label]) => <tr key={key}><th scope="row"><button type="button" onClick={() => select('state', key, label)}>{label}</button></th><td>{number(snapshot.outcomes?.[key])}</td></tr>)}
      </tbody></table>
      <p className="muted">Snapshot {snapshot.snapshot_id || 'unavailable'} · Revision {snapshot.revision ?? 'unavailable'} · Recorded {snapshot.generated_at || 'time unavailable'}</p>
    </>}
    {available && selection && <Drawer title={selection.label} subtitle={`${number(matches.length)} matching original findings · Snapshot ${snapshot.snapshot_id || 'unavailable'}`} onClose={close}>
      <div className="contribution-findings">
        {matches.length === 0 ? <p>No matching findings are recorded in this snapshot.</p> : <ul>{matches.map(finding => <li key={finding.finding_id}>
          <strong>{finding.file || 'File unavailable'}</strong>
          <p>Rule {finding.rule_id || 'unavailable'} · {outcomes.find(([key]) => key === finding.state)?.[1] || 'Evidence unavailable'}</p>
          <p>Finding: {finding.finding_id}</p>
          <p>Proposal: {finding.proposal_id || 'Unavailable'} · Approval: {finding.approval_kind || 'Not recorded'}</p>
          {finding.reason && <p>{finding.reason}</p>}
        </li>)}</ul>}
      </div>
    </Drawer>}
  </section>
}

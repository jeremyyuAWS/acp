import { useId } from 'react'
import './remediation-run-insights.css'

const DEFAULT = { enabled: true, mode: 'review_all', minimum_reliability: null, max_review_attempts: 1,
  review_model: 'strong', permitted_families: [], evaluation_versions: {} }

export default function RemediationReviewPolicy({ value, onChange, disabled, supported = false,
  automaticSupported = false, automaticReason = '', administratorFloor = null, eligibleFamilies = [], standingApprovalEnabled = false }) {
  const id = useId()
  const policy = { ...DEFAULT, ...value }
  const available = automaticSupported && eligibleFamilies.length > 0
  const change = delta => onChange({ ...policy, ...delta })
  const selected = eligibleFamilies.filter(row => policy.permitted_families.includes(row.change_family)
    && policy.evaluation_versions[row.change_family] === row.evaluation_version)
  const floors = selected.map(row => row.minimum_reliability).filter(Number.isFinite)
  if (available && Number.isFinite(administratorFloor)) floors.push(administratorFloor)
  const minimum = floors.length ? Math.max(...floors) : 0
  const selectFamily = (row, checked) => {
    const families = policy.permitted_families.filter(family => family !== row.change_family)
    const versions = { ...policy.evaluation_versions }
    delete versions[row.change_family]
    if (checked) { families.push(row.change_family); versions[row.change_family] = row.evaluation_version }
    change({ permitted_families: families, evaluation_versions: versions })
  }
  return <fieldset disabled={disabled || !supported} className="remediation-review-policy">
    <legend>Ask another AI to review suggestions?</legend>
    <label><input type="checkbox" checked={policy.enabled} onChange={event => change({ enabled: event.target.checked, mode: 'review_all' })} />
      Check suggestions with a configured reviewer model</label>
    <p>Review calls use the same maximum spend for this run shown above. A model's agreement is not proof that a change is correct.</p>
    {!supported && <p>AI review is not available on this server yet.</p>}
    {policy.enabled && <>
      <label htmlFor={`${id}-attempts`}>If the reviewer is unsure or requests changes</label>
      <select id={`${id}-attempts`} value={policy.max_review_attempts} onChange={event => change({ max_review_attempts: Number(event.target.value) })}>
        <option value={1}>Send the suggestion to me</option>
        <option value={2}>Allow one final AI review, then send it to me</option>
      </select>
      <label htmlFor={`${id}-reviewer`}>Reviewer preference</label>
      <select id={`${id}-reviewer`} value={policy.review_model} onChange={event => change({ review_model: event.target.value })}>
        <option value="strong">Different configured model</option><option value="low_cost">Lowest-cost configured model</option>
      </select>
      <p>Calibration-based automatic application requires an independent reviewer accepting the exact version. Refusals, uncertain charges and spending limits stop further AI review. Unresolved disagreement goes to you.</p>
      <fieldset className="remediation-review-policy__mode">
        <legend>When should a person review AI changes?</legend>
        <label><input type="radio" name={`${id}-mode`} value="review_all" checked={policy.mode === 'review_all'}
          onChange={() => change({ mode: 'review_all' })} /> {standingApprovalEnabled ? 'Use the advance approval choice above' : 'Review all AI changes — default'}</label>
        <label><input type="radio" name={`${id}-mode`} value="threshold" checked={policy.mode === 'threshold'} disabled={!available}
          onChange={() => change({ mode: 'threshold' })} /> Automatically apply eligible, checked changes</label>
      </fieldset>
      {!available && <p className="remediation-review-policy__calibration-note">Calibration-based automatic application is not available for this run. Calibration path: {automaticReason || 'No change family has a supported objective writer, exact-version independent review and current evaluated reliability configured.'} {standingApprovalEnabled ? 'This does not change the advance approval choice above.' : 'AI suggestions will remain drafts for your approval.'}</p>}
      <details open={policy.mode === 'threshold'}><summary>Minimum validated reliability</summary>
        <p>This is based on evaluated results for this type of change. It is not the AI's own confidence and does not guarantee each change is correct.</p>
        <p>Choose eligible change types and an explicit threshold. Approve plan and start authorizes this bounded run policy; later settings changes cannot broaden an approved run.</p>
        {eligibleFamilies.length ? <fieldset disabled={!available}><legend>Eligible change types and evaluated reviewers</legend>
          {eligibleFamilies.map(row => <label key={`${row.change_family}:${row.evaluation_version}`}>
            <input type="checkbox" checked={selected.includes(row)} onChange={event => selectFamily(row, event.target.checked)} />
            {row.change_family} ({row.format}) · Reviewer: {row.reviewer_provider} / {row.reviewer_model} · Administrator minimum: {row.minimum_reliability}% · Evaluation: {row.evaluation_version}
          </label>)}
        </fieldset> : <p>Eligible change types: not configured. Validated reviewer configuration: unavailable.</p>}
        <label htmlFor={`${id}-threshold`}>Minimum validated reliability for automatic application</label>
        <input id={`${id}-threshold`} type="number" min={minimum} max={100} step="any" value={available ? (policy.minimum_reliability ?? '') : ''}
          placeholder="Not configured" disabled={!available}
          onChange={event => { const raw = event.target.value; const n = Number(raw); if (!raw) change({ minimum_reliability: null }); else if (Number.isFinite(n) && n >= minimum && n <= 100) change({ minimum_reliability: n }) }} />
        {floors.length > 0 && <p>The administrator minimum for your selected change types is {minimum}%.</p>}
        <p>Previewing settings makes no paid calls. Eligibility not yet known stays unknown until exact source, proposal, review and validation evidence is available. {standingApprovalEnabled ? 'These calibration requirements apply only to the threshold option. The advance approval choice above still uses the supported writer and verification checks.' : 'Subjective changes, stale evidence, failed checks and missing calibration still need your approval.'}</p>
      </details>
    </>}
  </fieldset>
}

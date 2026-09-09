import { useId } from 'react'
import './remediation-run-insights.css'

const DEFAULT = { enabled: false, mode: 'review_all', minimum_reliability: 95, max_review_attempts: 1 }

export default function RemediationReviewPolicy({ value, onChange, disabled, supported = false,
  automaticSupported = false, automaticReason = '', administratorFloor = 95 }) {
  const id = useId()
  const policy = { ...DEFAULT, ...value }
  const change = delta => onChange({ ...policy, ...delta })
  return <fieldset disabled={disabled || !supported} className="remediation-review-policy">
    <legend>Ask another AI to review suggestions?</legend>
    <label><input type="checkbox" checked={policy.enabled} onChange={event => change({ enabled: event.target.checked, mode: 'review_all' })} />
      Check suggestions with a different configured model</label>
    <p>Review calls use the same run spending limit. A model's agreement is not proof that a change is correct.</p>
    {!supported && <p>AI review is not available on this server yet.</p>}
    {policy.enabled && <>
      <label htmlFor={`${id}-attempts`}>If the reviewer is unsure or requests changes</label>
      <select id={`${id}-attempts`} value={policy.max_review_attempts} onChange={event => change({ max_review_attempts: Number(event.target.value) })}>
        <option value={1}>Send the suggestion to me</option>
        <option value={2}>Allow one final AI review, then send it to me</option>
      </select>
      <p>Refusals, uncertain charges and spending limits stop further AI review. The original suggestion remains available for your decision.</p>
      <fieldset className="remediation-review-policy__mode" disabled={!automaticSupported}>
        <legend>When may ACP skip your approval?</legend>
        <label><input type="radio" name={`${id}-mode`} value="review_all" checked={policy.mode === 'review_all'}
          onChange={() => change({ mode: 'review_all' })} /> Review every AI suggestion</label>
        <label><input type="radio" name={`${id}-mode`} value="threshold" checked={policy.mode === 'threshold'}
          onChange={() => change({ mode: 'threshold' })} /> Automatically apply only validated suggestions</label>
      </fieldset>
      {!automaticSupported && <p className="remediation-review-policy__calibration-note">{automaticReason || 'Automatic approval is unavailable until this change type has current calibration data, an independent check, and a supported writer.'} Suggestions will continue to come to you for approval.</p>}
      <details open={policy.mode === 'threshold'}><summary>Reliability threshold</summary>
        <p>{policy.mode === 'threshold'
          ? `ACP will require validated reliability of at least ${Math.max(administratorFloor, policy.minimum_reliability)}% before it can apply a suggestion. The administrator floor is ${administratorFloor}%.`
          : 'This preference is ready for a future validated-auto policy. Every AI suggestion still requires your approval today.'}</p>
        <label htmlFor={`${id}-threshold`}>Minimum validated reliability for automatic application</label>
        <input id={`${id}-threshold`} type="number" min={90} max={100} step={1} value={policy.minimum_reliability}
          disabled={!automaticSupported}
          onChange={event => { const n = Number(event.target.value); if (Number.isInteger(n) && n >= 90 && n <= 100) change({ minimum_reliability: n }) }} />
        <p>This uses measured validation evidence, never an AI's self-reported confidence. A higher threshold sends more work to you.</p>
      </details>
    </>}
  </fieldset>
}

import { useId } from 'react'
import './remediation-run-insights.css'

const DEFAULT = { enabled: false, mode: 'review_all', minimum_reliability: 95, max_review_attempts: 1 }

export default function RemediationReviewPolicy({ value, onChange, disabled, supported = false }) {
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
      <details><summary>Human-review threshold</summary>
        <p>Every AI suggestion still requires your approval. Automatic application needs validated reliability data and independent checks for the type of change; it is not available on this execution path.</p>
        <label htmlFor={`${id}-threshold`}>Preferred minimum validated reliability for future automatic application</label>
        <input id={`${id}-threshold`} type="number" min={90} max={100} step={1} value={policy.minimum_reliability}
          onChange={event => { const n = Number(event.target.value); if (Number.isInteger(n) && n >= 90 && n <= 100) change({ minimum_reliability: n }) }} />
        <p>This saves a preference only. It does not grant automatic approval or use an AI's self-reported confidence.</p>
      </details>
    </>}
  </fieldset>
}

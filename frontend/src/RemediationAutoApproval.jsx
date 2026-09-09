import { useId } from 'react'

export default function RemediationAutoApproval({ policy, onChange, disabled, supported = false, reason = '' }) {
  const id = useId()
  const checked = policy.auto_approve_ai === true
  const available = supported && policy.ai > 0 && Number(policy.ai_budget_usd) > 0
  return <fieldset className="remediation-auto-approval" disabled={disabled}>
    <label htmlFor={id}><input id={id} type="checkbox" checked={checked}
      disabled={!checked && !available} onChange={event => onChange('auto_approve_ai', event.target.checked)} />
      <strong>Automatically approve eligible AI suggestions</strong></label>
    <p>{checked ? 'Auto-approval on for this plan. Approve plan and start authorizes eligible suggestions throughout this run, including fallbacks, without more approval dialogs.'
      : 'Off by default. Turn on to give advance approval for eligible AI suggestions in this run.'}</p>
    {!available && <p>{!supported ? (reason || 'Automatic approval is unavailable on this server.') : 'Choose Rules + AI and a positive run spending limit to enable this option.'}</p>}
    <details><summary>Which suggestions can proceed?</summary>
      <p>Complete, current AI suggestions with a supported writer and a tracked Google Drive or SharePoint source are approved and applied to the working copy. This includes supported alternative text, link text, labels, slide titles, sensory-text changes and language tags in supported Office and PDF formats.</p>
      <p>Missing drafts, partial coverage, changed sources, unresolved optional AI reviews, unsupported changes and manual judgments still need you. Approval is not proof of correctness: the normal writer and verification checks remain. Publishing is a separate action.</p>
      <p>This applies only to the new run you start. Saving it as a default offers the same choice for future plans; it does not authorize existing runs.</p>
    </details>
  </fieldset>
}

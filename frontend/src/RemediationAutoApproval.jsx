import { useId } from 'react'
import RemediationOptionHelp from './RemediationOptionHelp.jsx'

export default function RemediationAutoApproval({ policy, onChange, disabled, supported = false, reason = '' }) {
  const id = useId()
  const checked = policy.auto_approve_ai === true
  const available = supported && policy.ai === 1 && policy.ai_budget_usd !== undefined
  return <fieldset className="remediation-auto-approval remediation-plan-option" disabled={disabled}>
    <label htmlFor={id}><input id={id} type="checkbox" checked={!checked}
      disabled={!checked && !available} onChange={event => onChange('auto_approve_ai', !event.target.checked)} />
      <strong>Review before applying</strong></label>
    <RemediationOptionHelp label="review before applying AI suggestions">
    <p>{checked ? 'Eligible generated fixes are automatically approved by default. Approve plan and start authorizes eligible suggestions throughout this run, including fallbacks, without more approval dialogs.'
      : 'Review before applying is on. Generated AI suggestions wait for your approval. Turn it off to automatically approve eligible suggestions under the plan you accept.'}</p>
    {!available && <p>{!supported ? (reason || 'Automatic approval is unavailable on this server.') : 'Choose Rules + AI and a run spending limit to enable this option. Local AI does not require a paid budget.'}</p>}
    <strong>Which suggestions can proceed?</strong>
      <p>Complete, current AI suggestions with a supported writer and a tracked Google Drive or SharePoint source are approved and applied to the working copy. This includes supported alternative text, link text, labels, slide titles, sensory-text changes and language tags in supported Office and PDF formats.</p>
      <p>Missing drafts, partial coverage, changed sources, unresolved AI reviews, unsupported changes and manual judgments still need you. If you enable optional AI review, its result must be accepted before application. Approval is not proof of correctness: the reviewer checks the draft, not the finished document, and the normal writer and verification checks remain. Publishing is a separate action.</p>
      <p>This applies only to the new run you start. Saving it as a default offers the same choice for future plans; it does not authorize existing runs.</p>
    </RemediationOptionHelp>
  </fieldset>
}

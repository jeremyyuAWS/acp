import { useId } from 'react'
import RemediationOptionHelp from './RemediationOptionHelp.jsx'

export default function RemediationAutoApproval({ policy, onChange, disabled, supported = false, reason = '' }) {
  const id = useId()
  const checked = policy.auto_approve_ai === true
  // The AI reviewer is REQUIRED for this path, not optional: nothing shows an
  // auto-approved suggestion to a person before it is applied and released, so the
  // reviewer is the only remaining check on the draft. The server refuses to save a
  // policy without it, so gate the control here rather than letting Save throw.
  const reviewed = policy.ai_review?.enabled === true
  const available = policy.ai_zone !== 'local' && supported && policy.ai > 0 && Number(policy.ai_budget_usd) > 0 && reviewed
  return <fieldset className="remediation-auto-approval remediation-plan-option" disabled={disabled}>
    <label htmlFor={id}><input id={id} type="checkbox" checked={!checked}
      disabled={!checked && !available} onChange={event => onChange('auto_approve_ai', !event.target.checked)} />
      <strong>Review before applying</strong></label>
    <RemediationOptionHelp label="review before applying AI suggestions">
    <p>{checked ? 'Eligible generated fixes are automatically approved by default. Approve plan and start authorizes eligible suggestions throughout this run, including fallbacks, without more approval dialogs.'
      : 'Review before applying is on. Generated AI suggestions wait for your approval. Turn it off to automatically approve eligible suggestions after the AI reviewer accepts them.'}</p>
    {!available && <p>{policy.ai_zone === 'local' ? 'Local Ollama drafts require your review; no cloud reviewer is used.' : !supported ? (reason || 'Automatic approval is unavailable on this server.')
      : !(policy.ai > 0 && Number(policy.ai_budget_usd) > 0) ? 'Choose Rules + AI and a positive run spending limit to enable this option.'
      : 'Turn on AI review in the AI options first. Nobody reads an automatically approved suggestion before it is applied, so the reviewer is required for this option.'}</p>}
    <strong>Which suggestions can proceed?</strong>
      <p>Complete, current AI suggestions with a supported writer and a tracked Google Drive or SharePoint source are approved and applied to the working copy. This includes supported alternative text, link text, labels, slide titles, sensory-text changes and language tags in supported Office and PDF formats.</p>
      <p>Missing drafts, partial coverage, changed sources, unresolved AI reviews, unsupported changes and manual judgments still need you. A suggestion the AI reviewer has not accepted is never approved this way. Approval is not proof of correctness: the reviewer checks the draft, not the finished document, and the normal writer and verification checks remain. Publishing is a separate action.</p>
      <p>This applies only to the new run you start. Saving it as a default offers the same choice for future plans; it does not authorize existing runs.</p>
    </RemediationOptionHelp>
  </fieldset>
}

import './simple-remediation-questions.css'
import { useId } from 'react'
import RemediationOptionHelp from './RemediationOptionHelp.jsx'
import RemediationReviewPolicy from './RemediationReviewPolicy.jsx'
import RemediationAutoApproval from './RemediationAutoApproval.jsx'
import RemediationGenerationChain from './RemediationGenerationChain.jsx'
import RemediationModeDiagram from './RemediationModeDiagram.jsx'

const MODES = [
  ['Review every change', 'Prepare proposed fixes. A person approves each change before application.'],
  ['Automate safe fixes', 'Apply eligible rule-based fixes only when qualifying validation evidence is available. Review the rest.'],
  ['Maximize automation', 'Apply all supported, eligible rule-based fixes, then verify. Human judgment and AI suggestions still need review.'],
]

export function RetiredRemediationPlanChoices({ policy, providers, disabled, onChange }) {
  const id = useId()
  return <div className="remediation-plan-choices">
    <fieldset disabled={disabled}>
      <legend>1. How much control do you want?</legend>
      <div className="remediation-plan-choices__grid">
        {MODES.map(([label, description], value) => <label key={label} className={policy.rule_based === value ? 'is-selected' : ''}>
          <input type="radio" name={`${id}-control`} checked={policy.rule_based === value} onChange={() => onChange('rule_based', value)} />
          <span><strong>{label}</strong><span>{description}</span></span>
        </label>)}
      </div>
    </fieldset>
    <fieldset disabled={disabled}>
      <legend>2. Where may AI process your content?</legend>
      <div className="remediation-plan-choices__grid remediation-plan-choices__grid--two">
        <label className={policy.ai === 0 ? 'is-selected' : ''}>
          <input type="radio" name={`${id}-ai`} checked={policy.ai === 0} onChange={() => onChange('ai', 0)} />
          <span><strong>No AI</strong><span>Use rule-based remediation only. Generate no new AI drafts in this planned run.</span></span>
        </label>
        <label className={policy.ai > 0 ? 'is-selected' : ''}>
          <input type="radio" name={`${id}-ai`} checked={policy.ai > 0} onChange={() => onChange('ai', 1)} />
          <span><strong>Use configured AI</strong><span>Prepare suggestions using the text and image providers shown below. A person must approve AI suggestions.</span></span>
        </label>
      </div>
      <p>Private-only and cloud-only routing cannot yet be selected for an individual run. These settings do not certify a provider as approved for confidential content.</p>
    </fieldset>
    {policy.ai > 0 && <section className="remediation-plan-choices__providers" aria-labelledby={`${id}-providers`}>
      <h3 id={`${id}-providers`}>3. AI providers &amp; budget</h3>
      <p>These are the configured destinations. Provider selection is managed in application settings.</p>
      <dl>{[['text', 'Text drafting'], ['vision', 'Image drafting']].map(([key, label]) => <div key={key}>
        <dt>{label}</dt><dd><strong>{providers?.[key]?.provider || 'Provider not reported'}</strong>
          {' · '}{providers?.[key]?.model || 'Model not reported'}
          <span>{providers?.[key]?.zone === 'cloud' ? 'Cloud destination' : providers?.[key]?.zone ? `Reported processing zone: ${providers[key].zone}` : 'Processing location not reported'} · Connection not tested</span>
        </dd>
      </div>)}</dl>
      <details><summary>What may be shared?</summary><p>AI drafting can send document text or images needed for a suggestion to the configured providers. This preview does not report the exact payload. If those destinations are unsuitable for the content, choose No AI.</p></details>
      <div className="remediation-plan-choices__budget"><strong>Run spending limit: unavailable</strong><p>This run cannot enforce a spending cap or pause AI at a budget limit. A cost estimate is not available. Choose No AI if a firm cap is required.</p></div>
    </section>}
    <section className="remediation-plan-choices__summary" aria-labelledby={`${id}-summary`}>
      <h3 id={`${id}-summary`}>Your remediation plan</h3>
      <p>{MODES[policy.rule_based][1]} {policy.ai === 0 ? 'No new AI drafts will be generated.' : 'Use the configured AI providers to prepare suggestions. No per-run spending cap is enforced.'}</p>
      <p>Changing this plan previews the work. Start remediation to apply it.</p>
    </section>
  </div>
}

// The previous detailed panel is retained above for restoration, but is no longer mounted.
export default function RemediationPlanChoices({ policy, disabled, onChange, generationChainOptions, budgetSupported = false, reviewSupported = false, automaticReviewSupported = false, automaticReviewReason = '', reviewAdministratorFloor = null, reviewEligibleFamilies = [], standingApprovalSupported = false, standingApprovalReason = '' }) {
  const id = useId()
  return <div className="remediation-plan-choices">
    <fieldset disabled={disabled}>
      <legend>1. Which changes may ACP apply?</legend>
      <div className="remediation-plan-choices__grid remediation-plan-choices__grid--two">
        <div className="remediation-plan-option">
          <label className={policy.rule_based === 0 ? 'is-selected' : ''}>
            <input type="radio" name={`${id}-automation`} checked={policy.rule_based === 0} onChange={() => onChange('rule_based', 0)} />
            <span><strong>Review every change</strong><span>Approve proposed changes before they are applied.</span></span>
          </label>
          <RemediationOptionHelp label="review before applying">You approve every proposed fix before application. AI is a separate choice below.</RemediationOptionHelp>
        </div>
        <div className="remediation-plan-option">
          <label className={policy.rule_based === 2 ? 'is-selected' : ''}>
            <input type="radio" name={`${id}-automation`} checked={policy.rule_based === 2} onChange={() => onChange('rule_based', 2)} />
            <span><strong>Apply rule-based fixes automatically</strong><span>Apply supported fixes, verify the results, and review the rest.</span></span>
          </label>
          <RemediationOptionHelp label="apply and verify automatically">ACP applies supported fixes using set rules and checks the result. AI suggestions and issues that need a person’s judgment still go to review.</RemediationOptionHelp>
        </div>
      </div>
    </fieldset>
    <fieldset disabled={disabled}>
      <legend>2. May ACP also try AI?</legend>
      <div className="remediation-plan-choices__grid remediation-plan-choices__grid--two">
        <div className="remediation-plan-option">
          <label className={policy.ai === 0 ? 'is-selected' : ''}>
            <input type="radio" name={`${id}-ai`} checked={policy.ai === 0} onChange={() => onChange('ai', 0)} />
            <span><strong>Rules only</strong><span>Use rules without generating AI suggestions.</span></span>
          </label>
          <RemediationOptionHelp label="rules only">Use only fixes based on set rules. ACP will not ask AI to write new suggestions for this run. Your approval choice above still applies.</RemediationOptionHelp>
        </div>
        <div className="remediation-plan-option">
          <label className={policy.ai > 0 ? 'is-selected' : ''}>
            <input type="radio" name={`${id}-ai`} checked={policy.ai > 0} onChange={() => onChange('ai', 1)} />
            <span><strong>Rules + AI waterfall</strong><span>Draft suggestions; try a fallback if needed. Choose how to approve below.</span></span>
          </label>
          <RemediationOptionHelp label="AI waterfall">A waterfall tries AI in stages, with up to {policy.generation_chain?.steps?.length === 3 ? 'three' : 'two'} generation models for a supported text suggestion. Later models run only after an empty or incomplete suggestion. Spending limits and availability still apply. Your approval choice below applies throughout the run. Document text or images may be sent to the configured providers; choose Rules only if those destinations are unsuitable for the content.</RemediationOptionHelp>
        </div>
      </div>
      {policy.ai > 0 && <div className="simple-remediation-budget">
        <label htmlFor={`${id}-budget`}>AI spending limit for this run (USD)</label>
        <input id={`${id}-budget`} type="number" min="0" max="1000000" step="0.01"
          disabled={disabled || !budgetSupported} value={budgetSupported ? (policy.ai_budget_usd ?? '0.00') : ''}
          onChange={event => onChange('ai_budget_usd', event.target.value)}
          placeholder={budgetSupported ? '0.00' : 'Unavailable'} aria-describedby={`${id}-budget-note`} />
        <p id={`${id}-budget-note`}>{budgetSupported
          ? 'AI pauses when the remaining budget cannot cover a request. Rule-based fixes continue. $0 permits no paid AI requests. Infrastructure costs are separate.'
          : 'Spending limits are not available on this server. Choose Rules only if you need a firm cap.'}</p>
      </div>}
    </fieldset>
    {/* What each automation choice above actually costs the reviewer, as one matrix. The point a
        reader is meant to take from it is the bottom row: with standing approval on, ACP does not
        stop to ask about AI suggestions. `activeModeId` is DERIVED from the live policy rather than
        stored, so the highlighted row cannot drift from the radios above it. Publishing stays a
        person's step in every row — the backstop that makes the automated row safe to choose. */}
    <RemediationModeDiagram activeModeId={policy.ai > 0 && policy.auto_approve_ai === true ? 'end-to-end'
      : policy.rule_based === 0 ? 'review-every-change' : 'rule-based-auto'} />
    <RemediationAutoApproval policy={policy} onChange={onChange} disabled={disabled}
      supported={standingApprovalSupported && budgetSupported} reason={standingApprovalReason} />
    {policy.ai > 0 && <RemediationGenerationChain policy={policy} options={generationChainOptions} disabled={disabled} budgetSupported={budgetSupported} onChange={onChange} />}
    {policy.ai > 0 && reviewSupported && <details><summary>Optional AI review and approval threshold</summary><RemediationReviewPolicy value={policy.ai_review} onChange={value => onChange('ai_review', value)}
      disabled={disabled || !budgetSupported} supported={reviewSupported} automaticSupported={automaticReviewSupported} standingApprovalEnabled={policy.auto_approve_ai === true}
      automaticReason={automaticReviewReason} administratorFloor={reviewAdministratorFloor} eligibleFamilies={reviewEligibleFamilies} /></details>}

  </div>
}

// Retired by request: the sticky approval bar and choices already explain this plan.
// Keep the previous summary available for a deliberate one-commit restoration.
export function RetiredRemediationPlanSummary({ policy, budgetSupported = false }) {
  const id = useId()
  return (
    <section className="remediation-waterfall-plan" aria-labelledby={`${id}-plan`}>
      <h3 id={`${id}-plan`}>Plan you are approving</h3>
      <ol>
        <li>{policy.rule_based === 0 ? 'Prepare rule-based changes for your approval.' : 'Apply eligible rule-based fixes and check the results.'}</li>
        {policy.ai > 0 && <li>For supported issues needing more help, prepare an AI suggestion. If the response is incomplete, try one more model when the budget allows.</li>}
        {policy.ai > 0 && policy.ai_review?.enabled && <li>Ask a different configured model to review the suggestion{policy.ai_review.max_review_attempts === 2 ? ', with at most one final review if needed' : ''}, within the same spending limit. Send the result to you for approval.</li>}
        <li>{policy.ai > 0 ? 'Review and edit AI suggestions. Handle remaining issues yourself.' : 'Review remaining issues. No new AI suggestions will be requested.'}</li>
      </ol>
      {policy.ai > 0 && <p>{budgetSupported
        ? Number(policy.ai_budget_usd || 0) === 0
          ? 'Your AI limit is $0. No paid AI attempts will run until you increase it.'
          : 'AI attempts use the spending limit above. If AI is unavailable or the budget runs out, rule-based work can continue.'
        : 'A capped AI waterfall is not available on this server yet. Choose Rules only to proceed without AI.'}</p>}
      <p className="remediation-waterfall-plan__note">Selecting options updates the preview. Choose “Approve plan and start” to begin. The preview is not a promise that every issue will be fixed.</p>
      {policy.ai > 0 && <p className="remediation-waterfall-plan__note">Additional issues AI may help resolve and expected AI spending are not estimated yet.</p>}
    </section>
  )
}

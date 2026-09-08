import './simple-remediation-questions.css'
import { useId } from 'react'

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
export default function RemediationPlanChoices({ policy, disabled, onChange, budgetSupported = false }) {
  const id = useId()
  return <div className="remediation-plan-choices">
    <fieldset disabled={disabled}>
      <legend>1. How should fixes be approved?</legend>
      <div className="remediation-plan-choices__grid remediation-plan-choices__grid--two">
        <label className={policy.rule_based === 0 ? 'is-selected' : ''}>
          <input type="radio" name={`${id}-automation`} checked={policy.rule_based === 0} onChange={() => onChange('rule_based', 0)} />
          <span><strong>Review before applying</strong><span>Approve proposed changes before they are applied.</span></span>
        </label>
        <label className={policy.rule_based === 2 ? 'is-selected' : ''}>
          <input type="radio" name={`${id}-automation`} checked={policy.rule_based === 2} onChange={() => onChange('rule_based', 2)} />
          <span><strong>Apply and verify automatically</strong><span>Apply eligible fixes and verify results. Changes that require human judgment stay in review.</span></span>
        </label>
      </div>
    </fieldset>
    <fieldset disabled={disabled}>
      <legend>2. Use AI to resolve more issues?</legend>
      <div className="remediation-plan-choices__grid remediation-plan-choices__grid--two">
        <label className={policy.ai === 0 ? 'is-selected' : ''}>
          <input type="radio" name={`${id}-ai`} checked={policy.ai === 0} onChange={() => onChange('ai', 0)} />
          <span><strong>Off</strong><span>Use rule-based fixes only.</span></span>
        </label>
        <label className={policy.ai > 0 ? 'is-selected' : ''}>
          <input type="radio" name={`${id}-ai`} checked={policy.ai > 0} onChange={() => onChange('ai', 1)} />
          <span><strong>On</strong><span>Prepare AI suggestions for review.</span></span>
        </label>
      </div>
      {policy.ai > 0 && <div className="simple-remediation-budget">
        <label htmlFor={`${id}-budget`}>Maximum AI spend for this run (USD)</label>
        <input id={`${id}-budget`} type="number" min="0" max="1000000" step="0.01"
          disabled={disabled || !budgetSupported} value={budgetSupported ? (policy.ai_budget_usd ?? '0.00') : ''}
          onChange={event => onChange('ai_budget_usd', event.target.value)}
          placeholder={budgetSupported ? '0.00' : 'Unavailable'} aria-describedby={`${id}-budget-note`} />
        <p id={`${id}-budget-note`}>{budgetSupported
          ? 'AI pauses when the remaining budget cannot cover another request. Rule-based fixes continue. $0 permits no paid AI requests. Infrastructure costs are separate.'
          : 'Spending limits are not available on this server. Choose Off if you need a firm cap.'}</p>
      </div>}
    </fieldset>
  </div>
}

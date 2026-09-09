import { useId } from 'react'
import { generationSteps, secondFallbackModels, secondFallbackUnavailable, generationChainProblem, withSecondFallback } from './remediationGenerationChain.js'
import './remediation-generation-chain.css'

export default function RemediationGenerationChain({ policy, options, disabled, budgetSupported, onChange }) {
  const id = useId()
  const steps = generationSteps(policy, options)
  const enabled = steps.length === 3
  const models = secondFallbackModels(policy, options)
  const unavailable = secondFallbackUnavailable(policy, options, budgetSupported)
  const problem = generationChainProblem(policy, options, budgetSupported)
  const current = steps[2]
  const currentModel = options?.models?.find(model => model.provider === current?.provider && model.model === current?.model)
  const currentIndex = models.findIndex(model => model.provider === current?.provider && model.model === current?.model)
  return <details className="remediation-generation-chain">
    <summary>AI options · {enabled ? 'Fallback 2 on' : 'Fallback 2 off'}</summary>
    <p>Try up to three models when earlier suggestions are unusable.</p>
    {steps.length >= 2 ? <ol aria-label="Configured generation models">{steps.map((step, index) => <li key={step.step_id || index}>
      <strong>{['Primary', 'Fallback 1', 'Fallback 2'][index]}</strong>
      <span>{step.provider} · {step.model}</span>
      <small>{options?.models?.some(model => model.provider === step.provider && model.model === step.model && model.allowed === true)
        ? 'Allowed' : 'Access unconfirmed'}</small>
    </li>)}</ol> : <p>Configured generation models are not reported by this server.</p>}
    <label className="remediation-generation-chain__toggle">
      <input type="checkbox" checked={enabled} disabled={disabled || (!enabled && !!unavailable)}
        aria-describedby={`${id}-reason`} onChange={event => onChange('generation_chain', withSecondFallback(policy, options, event.target.checked ? models[0] : null))} />
      Use fallback 2
    </label>
    {enabled && <label className="remediation-generation-chain__model">Second fallback model
      <select value={currentIndex < 0 ? '' : currentIndex} disabled={disabled || !!unavailable}
        onChange={event => { const model = models[Number(event.target.value)]; if (model) onChange('generation_chain', withSecondFallback(policy, options, model)) }}>
        {currentIndex < 0 && <option value="">Selected model unavailable</option>}
        {models.map((model, index) => <option key={`${model.provider}/${model.model}`} value={index}>{model.provider} · {model.model}</option>)}
      </select>
    </label>}
    {enabled && currentModel?.access_verified !== true && <p role="note">{currentModel?.reason || 'Account access to the selected second fallback has not been tested. No paid access check is made from this preview.'}</p>}
    <p id={`${id}-reason`}>{problem || unavailable || 'Available for supported text findings.'}</p>
    {/* Do not remove without replacing: this is the only place the plan states how many
        paid models a suggestion can cost and what the run cap is. It was dropped once in
        the same change that raised the default from two models to three. */}
    <p>Up to {enabled ? 3 : 2} generation models per supported text suggestion, plus the AI
      review if it is on. Transport retries are separate. The run spending limit remains
      ${policy.ai_budget_usd ?? '0.00'}.</p>
    <small>Changing this plan makes no paid requests. Existing accepted runs keep their original model chain.</small>
  </details>
}

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
  const currentIndex = models.findIndex(model => model.provider === current?.provider && model.model === current?.model)
  return <details className="remediation-generation-chain">
    <summary>AI options · {enabled ? 'Second fallback enabled' : 'Second fallback off'}</summary>
    <p>Try another model only when earlier models return an empty or incomplete suggestion. All steps share the run spending limit.</p>
    {steps.length >= 2 ? <ol aria-label="Configured generation models">{steps.map((step, index) => <li key={step.step_id || index}>
      <strong>{['Primary', 'Fallback 1', 'Fallback 2'][index]}</strong>
      <span>{step.provider} · {step.model}</span>
      <small>{options?.models?.some(model => model.provider === step.provider && model.model === step.model && model.allowed === true)
        ? 'Provider permitted by current settings' : 'Provider permission not confirmed'}</small>
    </li>)}</ol> : <p>Configured generation models are not reported by this server.</p>}
    <label className="remediation-generation-chain__toggle">
      <input type="checkbox" checked={enabled} disabled={disabled || (!enabled && !!unavailable)}
        aria-describedby={`${id}-reason`} onChange={event => onChange('generation_chain', withSecondFallback(policy, options, event.target.checked ? models[0] : null))} />
      Enable a second fallback
    </label>
    {enabled && <label className="remediation-generation-chain__model">Second fallback model
      <select value={currentIndex < 0 ? '' : currentIndex} disabled={disabled || !!unavailable}
        onChange={event => { const model = models[Number(event.target.value)]; if (model) onChange('generation_chain', withSecondFallback(policy, options, model)) }}>
        {currentIndex < 0 && <option value="">Selected model unavailable</option>}
        {models.map((model, index) => <option key={`${model.provider}/${model.model}`} value={index}>{model.provider} · {model.model}</option>)}
      </select>
    </label>}
    <p id={`${id}-reason`}>{problem || unavailable || 'Available for the supported text findings in this scope. Other formats and findings keep their supported path.'}</p>
    <p>Up to {enabled ? 3 : 2} generation models per supported text suggestion; transport retries and AI review are separate. The run spending limit remains ${policy.ai_budget_usd ?? '0.00'}.</p>
    <small>Changing this plan makes no paid requests. Existing accepted runs retain their original model chain.</small>
  </details>
}

const IDS = ['primary', 'fallback_1', 'fallback_2']
const sameModel = (a, b) => a?.provider === b?.provider && a?.model === b?.model
const validStep = (step, position) => step?.step_id === IDS[position] && step.position === position
  && step.enabled === true && typeof step.provider === 'string' && !!step.provider.trim()
  && typeof step.model === 'string' && !!step.model.trim()
  && Array.isArray(step.capabilities) && step.capabilities.length === 1 && step.capabilities[0] === 'text'
const allowedModel = model => model?.allowed === true && model.available === true && model.capabilities?.includes('text')
export function generationSteps(policy, options) {
  if (policy?.ai_zone === 'local') return []
  // The server owns the default chain. `chain_options` appends fallback_2 to
  // default_steps and only THEN sets supported:true (api/ai_generation_chain.py), so a
  // supported catalog always already carries three steps. A client-side append for
  // "supported with two steps" describes a response the server cannot produce, and
  // duplicating the default in two layers means a later server change silently
  // disagrees with the client. An explicit saved policy still wins.
  const steps = policy?.generation_chain?.steps ?? options?.default_steps
  if (!Array.isArray(steps)) return []
  // The server builds the default without knowing this run's cap, and permission can be
  // revoked after the catalog was built. A third position the run cannot pay for, or
  // whose model is no longer permitted, must not arrive PRE-SELECTED -- that is a paid
  // step nobody chose. Trim only the SERVER default; a saved generation_chain is what an
  // accepted run relies on and is never rewritten here.
  if (!policy?.generation_chain && steps.length === 3
    && (!(Number(policy?.ai_budget_usd) > 0)
      || !options?.models?.some(model => sameModel(steps[2], model) && allowedModel(model))))
    return steps.slice(0, 2)
  return steps
}
export function secondFallbackModels(policy, options) {
  const first = generationSteps(policy, options).slice(0, 2)
  if (first.length !== 2 || !first.every(validStep) || first[0].provider !== first[1].provider) return []
  return (options?.models || []).filter(model => allowedModel(model) && model.provider === first[0].provider
    && !first.some(step => sameModel(step, model)))
}
export function secondFallbackUnavailable(policy, options, budgetSupported) {
  if (options?.version !== 1 || options?.supported !== true || options?.max_steps !== 3)
    return options?.reason || 'A second fallback is not available for this scope on this server.'
  const first = generationSteps(policy, options).slice(0, 2)
  if (first.length !== 2 || !first.every(validStep) || sameModel(first[0], first[1])
    || first.some(step => !options?.models?.some(model => sameModel(step, model) && allowedModel(model))))
    return 'The primary and first fallback must be available, permitted text models.'
  if (!budgetSupported) return 'An enforced AI spending limit is required.'
  if (!/^\d{1,7}(?:\.\d{1,2})?$/.test(String(policy.ai_budget_usd ?? ''))
    || Number(policy.ai_budget_usd) <= 0 || Number(policy.ai_budget_usd) > 1000000)
    return 'Set a positive AI spending limit to enable another generation step.'
  if (!secondFallbackModels(policy, options).length) return 'No distinct, permitted text model is available for a second fallback.'
  return null
}
export function generationChainProblem(policy, options, budgetSupported) {
  if (!policy?.generation_chain || policy.ai === 0) return null
  const chain = policy.generation_chain
  const steps = chain.steps
  if (chain.version !== 1 || !Array.isArray(steps) || ![2, 3].includes(steps.length)
    || !steps.every(validStep) || steps.some(step => step.provider !== steps[0].provider)
    || new Set(steps.map(step => `${step.provider}\0${step.model}`)).size !== steps.length)
    return 'The selected model chain is invalid. Reset the plan before starting.'
  if (!steps.every(step => options?.models?.some(model => sameModel(step, model) && allowedModel(model))))
    return 'A selected model is no longer available or permitted. Reset the plan before starting.'
  if (steps.length === 3) return secondFallbackUnavailable(policy, options, budgetSupported)
  return null
}
export function withSecondFallback(policy, options, model) {
  const first = generationSteps(policy, options).slice(0, 2)
  return { version: 1, steps: [...first.map(step => ({ ...step, capabilities: [...step.capabilities] })),
    ...(model ? [{ step_id: 'fallback_2', position: 2, provider: model.provider, model: model.model, enabled: true, capabilities: ['text'] }] : [])] }
}

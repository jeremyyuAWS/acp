const rows = value => Array.isArray(value) ? value : []
const named = value => typeof value === 'string' && value.trim()
const key = values => encodeURIComponent(JSON.stringify(values))
const POSITIONS = ['primary', 'fallback_1', 'fallback_2']

// This projects recorded identity and configured positions, never timestamp-based causality.
export function recordedRunGraphGroups(runGraph) {
  if (runGraph?.contract_version !== 'remediation-run-graph.v1' || !['complete', 'partial'].includes(runGraph.coverage)) return null
  const attempts = [...new Map(rows(runGraph.attempts).filter(item => item && named(item.attempt_id)).map(item => [item.attempt_id, item])).values()]
  const consumed = new Set()
  const groups = []
  for (const [position, stepId] of POSITIONS.entries()) {
    const matches = rows(runGraph.chain_version === 1 ? runGraph.steps : []).filter(step => step && step.configured === true && step.step_id === stepId && step.position === position)
    if (matches.length !== 1) continue
    const step = matches[0]
    const ids = new Set(rows(step.attempt_ids))
    const linked = attempts.filter(attempt => ids.has(attempt.attempt_id) && attempt.step_id === stepId && attempt.generation_position === position && attempt.lineage_available === true && ['draft', 'fallback'].includes(attempt.purpose))
    if (step.enabled !== true && !linked.length) continue
    linked.forEach(attempt => consumed.add(attempt.attempt_id))
    groups.push([{
      id: `configured:${stepId}`, stage: position === 0 ? 'first' : 'next',
      role: position === 0 ? 'Initial AI' : `Fallback ${position}`,
      title: named(step.model) ? step.model : 'Model not recorded', provider: step.provider,
      model: step.model, stepId, attemptIds: linked.map(attempt => attempt.attempt_id), purpose: 'generation', identityKind: 'configured',
      detail: linked.length ? ({ suggestions_ready: 'Usable proposals recorded', failed: 'No usable result recorded', stopped: 'Attempt stopped' })[step.state] || 'Outcome not established' : 'Configured · dispatch not recorded',
      explanation: named(step.reason) ? step.reason : 'Recorded outcome unknown.',
      value: linked.length, metric: 'recorded attempts', canAnimate: false, in_flight: false,
    }])
  }
  const remaining = attempts.filter(attempt => !consumed.has(attempt.attempt_id))
  // All unpositioned generation models share one group. Their input order, model names,
  // and timestamps do not create a chain or assign numbered fallback positions.
  for (const purposes of [['draft', 'fallback'], ['review', 'final_review'], null]) {
    const selected = remaining.filter(attempt => purposes ? purposes.includes(attempt.purpose) : !['draft', 'fallback', 'review', 'final_review'].includes(attempt.purpose))
    const identities = new Map()
    for (const attempt of selected) {
      const id = key([attempt.purpose ?? null, attempt.provider ?? null, attempt.model ?? null])
      if (!identities.has(id)) identities.set(id, [])
      identities.get(id).push(attempt)
    }
    if (identities.size) groups.push([...identities].map(([id, records]) => {
      const first = records[0]
      const review = ['review', 'final_review'].includes(first.purpose)
      return {
        id: `recorded:${id}`, stage: review ? 'review' : first.purpose === 'draft' ? 'first' : first.purpose === 'fallback' ? 'next' : 'unknown',
        role: ({ draft: 'Recorded draft', fallback: 'Recorded fallback', review: 'AI review', final_review: 'Final AI review' })[first.purpose] || 'Other recorded AI activity',
        title: named(first.model) ? first.model : 'Model not recorded', provider: first.provider,
        model: first.model, stepId: null, attemptIds: records.map(attempt => attempt.attempt_id), purpose: first.purpose, identityKind: 'recorded',
        detail: review ? 'Recorded review · inspect outcome' : 'Position / sequence not recorded',
        value: records.length, metric: 'recorded attempts', canAnimate: false, in_flight: false,
      }
    }))
  }
  return groups
}

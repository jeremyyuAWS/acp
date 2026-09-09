import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import Choices from '../src/RemediationPlanChoices.jsx'
import '../src/styles.css'
import '../src/remediation-impact-card.css'
const models = ['Configured primary model', 'Configured first fallback', 'Configured second fallback']
const options = { version: 1, supported: !location.search.includes('unavailable'), reason: 'This scope has no supported slide-title findings.', max_steps: 3,
  default_steps: models.slice(0, 2).map((model, position) => ({ step_id: ['primary', 'fallback_1'][position], position, provider: 'Fixture provider', model, enabled: true, capabilities: ['text'] })),
  models: models.map(model => ({ provider: 'Fixture provider', model, allowed: true, available: true, capabilities: ['text'] })) }
window.fixturePolicies = []
function Fixture() {
  const [policy, setPolicy] = useState({ rule_based: 2, ai: 1, ai_budget_usd: '10.00' })
  return <main style={{ maxWidth: 640, margin: '24px auto', padding: 16 }}><h1>Plan</h1><Choices policy={policy} budgetSupported generationChainOptions={options}
    onChange={(key, value) => { const next = { ...policy, [key]: value }; window.fixturePolicies.push(next); setPolicy(next) }} /></main>
}
createRoot(document.getElementById('root')).render(<Fixture />)

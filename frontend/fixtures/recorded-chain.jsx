import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import RemediationWaterfallCard from '../src/RemediationWaterfallCard.jsx'
import RemediationWorkspaceTabs from '../src/RemediationWorkspaceTabs.jsx'
import '../src/styles.css'
const steps = ['primary', 'fallback_1', 'fallback_2'].map((step_id, position) => ({
  step_id, position, purpose: 'generation', configured: true, enabled: true,
  provider: 'recorded-provider', model: ['primary-model', 'first-fallback-model', 'second-fallback-model'][position],
  state: 'outcome_unknown', reason: 'Dispatch recorded; a current worker lease is not linked.', in_flight: false, attempt_ids: [`attempt-${position}`],
}))
const attempts = steps.map(step => ({ attempt_id: step.attempt_ids[0], step_id: step.step_id, generation_position: step.position,
  provider: step.provider, model: step.model, purpose: step.position ? 'fallback' : 'draft', lineage_available: true, status: 'started', spending_state: 'dispatched' }))
function Fixture() {
  const [state, setState] = useState(() => localStorage.getItem('chain-state') || 'running')
  const [second, setSecond] = useState(true)
  const snapshot = { scan_id: 'chain-scan', batch_id: 'chain-run', state, terminal: state !== 'running', generated_at: new Date().toISOString(),
    progress: { lease_healthy: true }, documents: { processing: state === 'running' ? 1 : 0 }, review: { items: 2 }, fixes: { verified: 3 }, finding_reconciliation: { exact: false } }
  const runGraph = { contract_version: 'remediation-run-graph.v1', coverage: 'complete', chain_version: 1,
    steps: steps.map(step => step.step_id === 'fallback_2' && !second ? { ...step, enabled: false, attempt_ids: [] } : step),
    attempts: [...attempts.filter(attempt => second || attempt.step_id !== 'fallback_2'), { attempt_id: 'reviewer-attempt', purpose: 'review', provider: 'review-provider', model: 'recorded-reviewer', status: 'started', spending_state: 'dispatched' }],
    review_receipts: [], edges: [], note: 'Synthetic fixture of the owner-scoped run graph contract.' }
  return <main style={{ maxWidth: 1440, margin: 'auto', padding: 16 }}>
    <h1>Saved chain fixture · synthetic records</h1>
    <label>Saved state <select aria-label="Saved state" value={state} onChange={e => { setState(e.target.value); localStorage.setItem('chain-state', e.target.value) }}>{['running', 'processing_complete', 'failed', 'cancelled'].map(s => <option key={s}>{s}</option>)}</select></label>
    <label><input type="checkbox" checked={second} onChange={e => setSecond(e.target.checked)} />Second fallback saved in plan</label>
    <RemediationWorkspaceTabs runId="chain-scan" snapshot={snapshot} plan={<p>Plan fixture</p>} review={<p>Review fixture</p>} live={<RemediationWaterfallCard snapshot={snapshot} activity={{ view: { available: true, ai_enabled: true, generated_at: snapshot.generated_at, stages: [], run_graph: runGraph } }} />} />
  </main>
}
createRoot(document.getElementById('root')).render(<Fixture />)

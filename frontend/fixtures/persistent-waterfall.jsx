import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import RemediationWaterfallCard from '../src/RemediationWaterfallCard.jsx'
import RemediationWorkspaceTabs from '../src/RemediationWorkspaceTabs.jsx'
import '../src/styles.css'
function Fixture() {
  const [state, setState] = useState(() => localStorage.getItem('fixture-run-state') || 'running')
  const [run, setRun] = useState('saved')
  const snapshot = { scan_id: 'saved-scan', run_id: 'saved-scan', batch_id: run === 'saved' ? 'saved-batch' : 'legacy-batch', state,
    terminal: ['processing_complete', 'failed', 'cancelled'].includes(state),
    generated_at: new Date().toISOString(), progress: { lease_healthy: true }, documents: { processing: state === 'running' ? 1 : 0 },
    review: { items: 2 }, fixes: { verified: 3 }, finding_reconciliation: { exact: false } }
  const activity = { view: { available: run === 'saved', ai_enabled: true, generated_at: snapshot.generated_at,
    stages: run === 'legacy' ? [] : [{ tier: 1, operations: 3, active: state === 'running' ? 1 : 0, settled: 2, models: [{ provider: 'recorded-provider', model: 'recorded-model-v1' }] }] } }
  return <main style={{ maxWidth: 1200, padding: 16, margin: 'auto' }}>
    <h1>Persistent waterfall fixture</h1>
    <label>Saved run state <select value={state} onChange={e => { setState(e.target.value); localStorage.setItem('fixture-run-state', e.target.value) }}>{['running', 'processing_complete', 'failed', 'cancelled', 'paused', 'stalled'].map(value => <option key={value}>{value}</option>)}</select></label>
    <label>Saved run <select aria-label="Saved run" value={run} onChange={e => setRun(e.target.value)}><option value="saved">Saved run</option><option value="legacy">Legacy run</option></select></label>
    <RemediationWorkspaceTabs runId="saved-scan" snapshot={snapshot} plan={<p>Plan fixture</p>} review={<p>Review fixture</p>}
      live={<RemediationWaterfallCard snapshot={snapshot} activity={activity} />} />
  </main>
}
createRoot(document.getElementById('root')).render(<Fixture />)

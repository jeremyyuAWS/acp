import React from 'react'
import { createRoot } from 'react-dom/client'
import RemediationWaterfallCard from '../src/RemediationWaterfallCard.jsx'
import '../src/styles.css'

const now = new Date().toISOString()
const snapshot = {
  run_id: 'fixture', scan_id: 'fixture', batch_id: 'fixture-batch', state: 'running',
  generated_at: now, progress: { lease_healthy: true }, documents: { processing: 1 },
  fixes: { verified: 2 }, review: { items: 3 }, finding_reconciliation: { exact: false },
}
const activity = { view: {
  available: true, ai_enabled: true, generated_at: now,
  stages: [
    { tier: 1, operations: 2, active: 1, models: [{ provider: 'recorded-provider', model: 'recorded-model-with-a-long-version-20260908' }] },
    { tier: 2, operations: 0, active: 0, models: [] },
  ],
} }
createRoot(document.getElementById('root')).render(<main style={{ maxWidth: 1200, margin: 'auto', padding: 12 }}>
  <h1>Remediate presentation fixture</h1>
  <RemediationWaterfallCard snapshot={snapshot} activity={activity} />
</main>)

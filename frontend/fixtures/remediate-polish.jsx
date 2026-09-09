import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import RemediationInbox from '../src/RemediationInbox.jsx'
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
const source = 'Source paragraph describing a long accessibility report. '.repeat(150) + 'Full source ending.'
const findings = Array.from({ length: 20 }, (_, index) => ({ id: index + 1, file: `Document-${Math.floor(index / 5) + 1}.docx`, title: 'DOCX · Passage language needs review', rule_id: '3.1.2', hasProposal: true, before: source, after: 'fr', rationale: 'Confirm the language of this passage before changing its metadata.' }))
function ReviewFixture() {
  const [decisions, setDecisions] = useState({})
  return <section id="review-fixture"><h2>Review fixture</h2><RemediationInbox queue={findings} decisions={decisions} onDecide={async (item, decision) => setDecisions(current => ({ ...current, [item.id]: decision }))} onRecheck={() => {}} /></section>
}
createRoot(document.getElementById('root')).render(<main style={{ maxWidth: 1200, margin: 'auto', padding: 12 }}>
  <h1>Remediate presentation fixture</h1>
  {new URLSearchParams(window.location.search).get('mode') === 'review' ? <ReviewFixture />
    : <RemediationWaterfallCard snapshot={snapshot} activity={activity} />}
</main>)

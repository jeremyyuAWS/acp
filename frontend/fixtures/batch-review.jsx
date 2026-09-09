import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import RemediationInbox from '../src/RemediationInbox.jsx'
import '../src/styles.css'
const items = Array.from({ length: 37 }, (_, i) => ({ id: `finding-${i}`, file: `Document ${String(i + 1).padStart(2, '0')}.docx`,
  title: 'Image needs alt text', ruleId: '1.1.1', hasProposal: true, before: 'No alternative text', after: `Chart showing quarterly revenue in document ${i + 1}.`,
  proposals: [{ before: 'No alternative text', proposed_value: `Chart showing quarterly revenue in document ${i + 1}.` }],
  _raw: { decision_version: 0, proposal_snapshot_ids: [`snapshot-${i}`], source_revision: 'fixture-source' } }))
window.fixtureDecisions = []
function Fixture() {
  const [queue, setQueue] = useState(items)
  return <main style={{ maxWidth: 1200, margin: '20px auto' }}><RemediationInbox queue={queue} decisions={{}} scanId="fixture"
    onDecide={async (f, d) => { window.fixtureDecisions.push({ id: f.id, decision: d }); setQueue(q => q.filter(x => x.id !== f.id)) }} /></main>
}
createRoot(document.getElementById('root')).render(<Fixture />)

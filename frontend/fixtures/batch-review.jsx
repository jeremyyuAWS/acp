import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import RemediationInbox from '../src/RemediationInbox.jsx'
import '../src/styles.css'
const items = Array.from({ length: 37 }, (_, i) => ({ id: `finding-${i}`, file: `Document ${String(i + 1).padStart(2, '0')}.docx`,
  title: 'Image needs alt text', ruleId: '1.1.1', hasProposal: true, before: 'No alternative text', after: `Chart showing quarterly revenue in document ${i + 1}.`,
  proposals: [{ before: 'No alternative text', proposed_value: `Chart showing quarterly revenue in document ${i + 1}.` }],
  _raw: { decision_version: 0, proposal_snapshot_ids: [`snapshot-${i}`], source_revision: 'fixture-source' } }))
const applied = Array.from({ length: 119 }, (_, i) => ({ id: `applied-${i}`, file: `Applied ${i}.docx`, autoApplied: true, after: 'Applied change' }))
const manual = { id: 'manual', file: 'manual.docx', title: 'Manual issue' }
window.fixtureDecisions = []
function Fixture() {
  const [queue, setQueue] = useState(new URLSearchParams(location.search).has('applied') ? applied : [...applied, ...items, manual])
  return <main style={{ maxWidth: 1200, margin: '20px auto' }}><RemediationInbox queue={queue} decisions={{}} scanId="fixture"
    onDecide={async (f, d) => { window.fixtureDecisions.push({ id: f.id, decision: d }); setQueue(q => q.filter(x => x.id !== f.id)) }} /></main>
}
createRoot(document.getElementById('root')).render(<Fixture />)

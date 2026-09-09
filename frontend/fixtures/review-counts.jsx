import React from 'react'
import { createRoot } from 'react-dom/client'
import Header from '../src/RemediationRunHeader.jsx'
import Inbox from '../src/RemediationInbox.jsx'
import { autoFixRows } from '../src/remediationInboxModel.js'
import { remediationReviewCounts, reviewBadgeTitle } from '../src/remediationCountSummary.js'
import '../src/styles.css'
const applied = autoFixRows(Array.from({ length: 2000 }, (_, i) => ({ file: `doc-${i % 177}.pptx`, rule_id: '2.4.6', after: 'Applied title' })))
const pending = Array.from({ length: 299 }, (_, i) => ({ id: `pending-${i}`, file: `doc-${i % 177}.pptx`, hasProposal: true, after: 'Proposed title', proposals: [{ proposed_value: 'Proposed title' }], _raw: { decision_version: 0, proposal_snapshot_ids: [`snapshot-${i}`], source_revision: 'source' } }))
const manual = Array.from({ length: 47 }, (_, i) => ({ id: `manual-${i}`, file: `doc-${i}.pptx`, title: 'Manual work' }))
const rows = [...pending, ...manual, ...applied], counts = remediationReviewCounts(rows)
window.fixtureWrites = 0
createRoot(document.getElementById('root')).render(<main style={{ maxWidth: 1200, margin: '20px auto' }}>
  <p title={reviewBadgeTitle(counts.pendingItems)}>{counts.pendingItems} review items requiring attention · {counts.documents} documents</p>
  <Header counts={{ autoFixed: 2400, documents: 177, needsApproval: counts.ready, manual: counts.manual, inspection: counts.inspection }} />
  <p>2,000 of 2,400 applied-change records loaded. Inspection does not approve a new change.</p>
  <Inbox queue={rows} decisions={{}} scanId="fixture" onDecide={async () => { window.fixtureWrites++; throw new Error('No writes expected') }} />
</main>)

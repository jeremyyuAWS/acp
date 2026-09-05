import { describe, expect, it } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import DiscoverRunProgress from './DiscoverRunProgress.jsx'
import AssessRunProgress from './AssessRunProgress.jsx'
import RemediationRunProgress from './RemediationRunProgress.jsx'

// One contract across all three workflow cards. Separate component tests protect each card's
// layout; this protects the handoff vocabulary they share. A future prop rename must not leave
// SharePoint visible in Discover while Assess or Remediate silently loses the selected estate.
const SCOPE = {
  kind: 'sharepoint',
  sites: [
    { id: 'clinical', name: 'Clinical', status: 'complete',
      libraries: [{ id: 'policies', name: 'Policies' }] },
    { id: 'research', name: 'Research', status: 'complete',
      libraries: [{ id: 'studies', name: 'Studies' }, { id: 'grants', name: 'Grants' }] },
  ],
}

const discover = () => renderToStaticMarkup(
  <DiscoverRunProgress source="sharepoint" scope={SCOPE} busy
    progress={{ phase: 'discovering', files_found: 42 }} />,
)

const assess = () => renderToStaticMarkup(
  <AssessRunProgress snapshot={{
    available: true, active: true, phase: 'assessing', source: 'sharepoint', scope: SCOPE,
    totals: { discovered: 42, eligible: 40 },
    kpis: { completed: 12, processing: 2 },
    queue: { in_flight: 2, queued: 26, workers: { busy: 2, max: 4 } },
  }} />,
)

const remediate = () => renderToStaticMarkup(
  <RemediationRunProgress source="sharepoint" scope={SCOPE}
    progress={{ total: 8, done: 3, failed: 0 }} />,
)

describe('SharePoint stays identified across the workflow', () => {
  it('carries the same multi-site estate through Discover, Assess, and Remediate', () => {
    const cards = [discover(), assess(), remediate()]
    for (const html of cards) {
      expect(html).toContain('Content source')
      expect(html).toContain('SharePoint')
      expect(html).toContain('Clinical')
      expect(html).toContain('Research')
      expect(html).toContain('3 document libraries')
    }
  })

  it('still renders the stage-specific live work around that shared source boundary', () => {
    expect(discover()).toContain('Build document inventory')
    expect(assess()).toContain('Opened and assessed documents')
    expect(remediate()).toContain('Automated remediation')
  })
})

import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import RemediationOpsPanel from './RemediationOpsPanel.jsx'
import { freshness, partitionSums, headline, isNewer, counterRows, secondaryRows }
  from './remediationSnapshot.js'

// The Remediation Real-Time Operations Panel. These tests are about the CONTRADICTIONS the panel
// exists to make impossible — a queued run reporting "Applying fixes", a SharePoint run labelled
// OneDrive, a telemetry gap rendered as an empty queue, a green "live" badge over a dead stream.
// Each of those was a real paint, and none of them was a rendering bug: they came from the browser
// assembling a story out of counters that belonged to different subsystems and different instants.

const SNAP = {
  run_id: 'scan-1', scan_id: 'scan-1', revision: 1757068800000,
  generated_at: '2026-09-05T12:00:00+00:00',
  state: 'running', reason: 'attempt_active', also: [], message: 'Remediation in progress',
  terminal: false,
  source: { provider: 'sharepoint', provider_label: 'SharePoint', sites: ['Legal'],
            libraries: ['Contracts'], scan_snapshot_id: 'scan-1',
            breadcrumb: 'SharePoint · Legal · Contracts' },
  total_documents: 10,
  documents: { completed: 4, processing: 2, waiting: 3, review: 1, failed: 0, skipped: 0 },
  fixes: { applied: 26, verified: 21, verification_failures: 5, documents_verified: 4 },
  delivery: { stored: 4, delivered: 3, pending: 1, eligible: 4, latest_at: null },
  review: { documents: 1, items: 2 },
  phases: [
    { key: 'preparing', label: 'Preparing', status: 'completed', detail: '10 documents in scope' },
    { key: 'applying', label: 'Applying approved fixes', status: 'active', detail: '2 in flight' },
    { key: 'rechecking', label: 'Re-checking corrected documents', status: 'active', detail: '21 of 26 fixes verified' },
    { key: 'saving', label: 'Saving corrected copies', status: 'active', detail: '1 pending delivery' },
    { key: 'finalizing', label: 'Finalizing evidence', status: 'pending', detail: null },
  ],
  active_attempts: [], retry_at: null, latest_progress_at: '2026-09-05T11:59:00+00:00',
  thresholds: { stall_after_s: 900, heartbeat_s: 15, delayed_after_s: 60 },
  integrity: { ok: true, violations: [], affected: [] },
}

const render = (props) => renderToStaticMarkup(createElement(RemediationOpsPanel, props))

describe('the panel renders the server snapshot and never assembles its own', () => {
  it('shows nothing before a snapshot exists, rather than an empty panel of zeroes', () => {
    expect(render({ snapshot: null })).toBe('')
    expect(render({ snapshot: { ...SNAP, state: 'draft' } })).toBe('')
  })

  it('renders the state, the phase rail and all six counters from one snapshot', () => {
    const html = render({ snapshot: SNAP, connected: true, receivedAt: Date.now() })
    expect(html).toContain('Remediation in progress')
    expect(html).toContain('Applying approved fixes')
    expect(html).toContain('10 in scope')
    for (const label of ['Completed', 'Processing', 'Waiting', 'Review', 'Failed', 'Skipped']) {
      expect(html).toContain(label)
    }
  })

  it('labels a SharePoint run SharePoint, never OneDrive', () => {
    const html = render({ snapshot: SNAP, connected: true, receivedAt: Date.now() })
    expect(html).toContain('SharePoint · Legal · Contracts')
    expect(html).not.toContain('OneDrive')
  })

  it('names the unit on every fix and delivery count', () => {
    const html = render({ snapshot: SNAP, connected: true, receivedAt: Date.now() })
    expect(html).toContain('Fixes applied')
    expect(html).toContain('Fixes verified')
    expect(html).toContain('Documents verified')
    expect(html).toContain('Corrected copies delivered')
    // A bare "Verified" is the ambiguity the PRD names: it was read as documents on one line and
    // as fixes on the next, from the same number.
    expect(html).not.toMatch(/>Verified</)
  })

  it('announces the headline only — not every counter increment', () => {
    const html = render({ snapshot: SNAP, connected: true, receivedAt: Date.now() })
    const live = html.match(/aria-live="polite"[^>]*>([^<]*)</g) || []
    expect(live.length).toBe(1)
    expect(live[0]).toContain('Remediation in progress')
  })

  it('carries every state in words, so nothing depends on colour alone', () => {
    const html = render({ snapshot: SNAP, connected: true, receivedAt: Date.now() })
    expect(html).toContain('In progress')     // phase status, spelled out beside the icon
    expect(html).toContain('Pending')
    expect(html).toContain('Live')            // freshness, spelled out beside the dot
  })
})

describe('a run with no active attempt cannot claim to be applying fixes', () => {
  it('shows the waiting state and no active applying phase', () => {
    const waiting = {
      ...SNAP, state: 'waiting', message: 'Waiting for processing capacity',
      documents: { completed: 0, processing: 0, waiting: 10, review: 0, failed: 0, skipped: 0 },
      phases: SNAP.phases.map((p) => p.key === 'applying'
        ? { ...p, status: 'pending', detail: '10 waiting' } : p),
    }
    const html = render({ snapshot: waiting, connected: true, receivedAt: Date.now() })
    expect(html).toContain('Waiting for processing capacity')
    expect(html).not.toContain('Applying approved fixes — In progress')
  })
})

describe('unknown and inconsistent are shown as themselves, never as zero or healthy', () => {
  it('renders an em dash for a counter the snapshot did not carry', () => {
    // Asserted on THAT counter's own cell, not on the page containing an em dash somewhere: the
    // phase rail renders one on every row, so `toContain('—')` passes whatever the counters say —
    // it was written as this check and did not fail when the null branch was deleted.
    const cell = (html, key) =>
      (html.match(new RegExp(`data-testid="rem-count-${key}"[^>]*>([^<]*)<`)) || [])[1]
    const partial = { ...SNAP, documents: { ...SNAP.documents, waiting: null } }
    const html = render({ snapshot: partial, connected: true, receivedAt: Date.now() })
    expect(cell(html, 'waiting')).toBe('—')
    expect(cell(html, 'completed')).toBe('4')
    // A real zero still reads as a zero — "unknown is not zero" must not turn into "zero is not
    // zero", which would hide a genuinely empty bucket.
    expect(cell(render({ snapshot: SNAP, connected: true, receivedAt: Date.now() }), 'failed'))
      .toBe('0')
  })

  it('names the affected metric and keeps the last confirmed values on screen', () => {
    const broken = { ...SNAP,
      integrity: { ok: false, affected: ['fixes'],
                   violations: [{ invariant: 'verified_within_applied', metric: 'fixes',
                                  detail: '30 verified fixes against 26 applied' }] } }
    const html = render({ snapshot: broken, connected: true, receivedAt: Date.now() })
    expect(html).toContain('Status temporarily inconsistent')
    expect(html).toContain('fixes')
    expect(html).toContain('last ACP confirmed')
    expect(html).toContain('26')          // the measured value survives the violation
  })

  it('says so when the counters do not add up to the scope', () => {
    const broken = { ...SNAP, total_documents: 12 }
    const html = render({ snapshot: broken, connected: true, receivedAt: Date.now() })
    expect(html).toContain('do not add up to the documents in scope')
  })
})

describe('freshness is the transport\'s answer, not an inference from the numbers', () => {
  const now = Date.parse('2026-09-05T12:00:00Z')

  it('is live only while the stream is open and the last update is recent', () => {
    expect(freshness({ snapshot: SNAP, connected: true, receivedAt: now - 5_000, now }).level)
      .toBe('live')
  })

  it('drops out of live the moment the stream disconnects, however fresh the numbers look', () => {
    // The case a green badge must not survive: the run went quiet at the same moment the stream
    // died, so every number on screen still looks current and none of them is being updated.
    const state = freshness({ snapshot: SNAP, connected: false, receivedAt: now - 2_000, now })
    expect(state.level).toBe('reconnecting')
    expect(state.detail).toContain('Last confirmed update 2s ago')
  })

  it('reports delayed once the last confirmed update passes the server\'s own threshold', () => {
    expect(freshness({ snapshot: SNAP, connected: true, receivedAt: now - 120_000, now }).level)
      .toBe('delayed')
  })

  it('reports the server\'s positive stall determination over anything measured here', () => {
    expect(freshness({ snapshot: { ...SNAP, state: 'stalled' }, connected: true,
                       receivedAt: now, now }).level).toBe('stalled')
  })

  it('is unknown — never zero, never healthy — with no snapshot or an unreconciled one', () => {
    expect(freshness({ snapshot: null, connected: true, now }).level).toBe('unknown')
    expect(freshness({ snapshot: { ...SNAP, integrity: { ok: false, violations: [], affected: [] } },
                       connected: true, receivedAt: now, now }).level).toBe('unknown')
  })
})

describe('the client normalizes and judges freshness; it never derives run state', () => {
  it('drops a frame whose revision went backwards', () => {
    expect(isNewer({ revision: 5 }, { revision: 4 })).toBe(false)
    expect(isNewer({ revision: 5 }, { revision: 5 })).toBe(true)
    expect(isNewer(null, { revision: 1 })).toBe(true)
    expect(isNewer({ revision: 5 }, null)).toBe(false)
  })

  it('answers "cannot check" rather than "checks out" when a counter is missing', () => {
    expect(partitionSums(SNAP)).toBe(true)
    expect(partitionSums({ ...SNAP, total_documents: 11 })).toBe(false)
    expect(partitionSums({ ...SNAP, documents: { ...SNAP.documents, waiting: null } })).toBe(null)
    expect(partitionSums({})).toBe(null)
  })

  it('omits a secondary metric it was not told, instead of showing it at zero', () => {
    const rows = secondaryRows({ fixes: { applied: 3 } })
    expect(rows.map((r) => r.key)).toEqual(['fixesApplied'])
  })

  it('returns null counters rather than zeroes when the snapshot carries none', () => {
    expect(counterRows({})).toBe(null)
    expect(counterRows({ documents: {} }).every((r) => r.value === null)).toBe(true)
  })

  it('keeps live progress visible under a more severe headline', () => {
    // Precedence decides the HEADLINE, not what the run is allowed to mention: "Review required"
    // over a run that is still fixing 2 documents would otherwise read as a stopped run.
    expect(headline({ ...SNAP, state: 'needs_attention', message: 'Review required',
                      also: ['running', 'waiting'] }))
      .toBe('Review required · 2 still processing · 3 waiting')
    expect(headline(SNAP)).toBe('Remediation in progress')
    expect(headline(null)).toBe(null)
  })
})

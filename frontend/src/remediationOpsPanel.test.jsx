import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import RemediationOpsPanel from './RemediationOpsPanel.jsx'
import { freshness, partitionSums, headline, isNewer, counterRows, secondaryRows }
  from './remediationSnapshot.js'

const here = dirname(fileURLToPath(import.meta.url))

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
    expect(html).toContain('10 documents in scope')
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
    // Reads the cell's TEXT, stripping the markup inside it. A known count is rendered through
    // LiveCounter (which wraps the number in spans so it can count up and flash "+N"), while an
    // unknown one is a bare em dash — so a matcher that only accepted a bare text node would
    // report every known counter as empty and pass this test for the wrong reason.
    const cell = (html, key) => {
      const open = html.indexOf(`data-testid="rem-count-${key}"`)
      if (open === -1) return undefined
      const start = html.indexOf('>', open) + 1
      const end = html.indexOf('</dd>', start)
      return html.slice(start, end).replace(/<[^>]*>/g, '').trim()
    }
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

describe('the panel shows what is being worked right now', () => {
  const withAttempts = (attempts) => ({
    ...SNAP, generated_at: '2026-09-05T12:00:00+00:00', active_attempts: attempts,
  })

  it('lists the in-flight documents rather than naming one current file', () => {
    // Remediation fans out across worker slots. Naming a single "current file" implies a serial
    // pipeline that does not exist — the defect PRD §17.7 is about.
    const html = render({ snapshot: withAttempts([
      { file: 'a.docx', phase: 'storing the corrected copy', attempt: 1,
        started_at: '2026-09-05T11:59:00+00:00', progress_at: '2026-09-05T11:59:50+00:00', elapsed_s: 60 },
      { file: 'b.pdf', phase: 're-verifying the corrected copy', attempt: 1,
        started_at: '2026-09-05T11:59:30+00:00', progress_at: '2026-09-05T11:59:58+00:00', elapsed_s: 30 },
    ]), connected: true, receivedAt: Date.now() })
    expect(html).toContain('In flight now')
    expect(html).toContain('2 documents')
    expect(html).toContain('a.docx')
    expect(html).toContain('b.pdf')
    expect(html).toContain('storing the corrected copy')
    expect(html).not.toContain('current file')
  })

  it('caps the list at three and counts the rest', () => {
    const many = Array.from({ length: 20 }, (_, i) => ({
      file: `doc-${i}.docx`, phase: 'applying', attempt: 1, elapsed_s: 10,
      started_at: '2026-09-05T11:59:00+00:00', progress_at: '2026-09-05T11:59:55+00:00' }))
    const html = render({ snapshot: withAttempts(many), connected: true, receivedAt: Date.now() })
    expect(html).toContain('doc-0.docx')
    expect(html).toContain('doc-2.docx')
    expect(html).not.toContain('doc-3.docx')
    expect(html).toContain('and 17 more documents in flight')
  })

  it('shows an attempt number only while retrying', () => {
    // Scoped to the in-flight LIST, not the whole page: the Processing counter's definition
    // tooltip reads "A valid worker attempt is actively changing…", so a bare
    // `not.toContain('attempt')` fails against unrelated copy and would have to be loosened
    // into something that no longer checks anything.
    const inFlight = (html) => {
      const start = html.indexOf('In flight now')
      return start === -1 ? '' : html.slice(start, html.indexOf('</ul>', start))
    }
    const first = render({ snapshot: withAttempts([{ file: 'a.docx', attempt: 1, elapsed_s: 5 }]),
                           connected: true, receivedAt: Date.now() })
    expect(inFlight(first)).toContain('a.docx')
    expect(inFlight(first)).not.toContain('attempt')
    const retry = render({ snapshot: withAttempts([{ file: 'a.docx', attempt: 3, elapsed_s: 5 }]),
                           connected: true, receivedAt: Date.now() })
    expect(inFlight(retry)).toContain('attempt 3')
  })

  it('calls the heartbeat a signal, not progress', () => {
    // store.touch_job bumps updated_at on every lease heartbeat, so progress_at means "last
    // touched". Labelling it "last progress" would let a worker that is merely alive read as one
    // that is getting somewhere — the distinction a stalled run turns on.
    const html = render({ snapshot: withAttempts([
      { file: 'a.docx', phase: 'applying', attempt: 1, elapsed_s: 90,
        progress_at: '2026-09-05T11:59:30+00:00' }]), connected: true, receivedAt: Date.now() })
    expect(html).toContain('last signal')
    expect(html).not.toContain('last progress')
  })

  it('renders nothing when no attempt is active', () => {
    const html = render({ snapshot: withAttempts([]), connected: true, receivedAt: Date.now() })
    expect(html).not.toContain('In flight now')
  })
})

describe('the durable lifecycle log is visible without becoming a second state model', () => {
  it('renders bounded event narration without adding another live region', () => {
    const events = [
      { key: '42', line: '4 fixes independently verified for Patient Guide.docx',
        kind: 'remediate.verified', tone: 'success', occurredAt: '2026-09-05T12:00:00Z' },
      { key: '41', line: 'Manual review requested for Form.pdf · WCAG 1.1.1',
        kind: 'remediate.review_requested', tone: 'attention', occurredAt: null },
    ]
    const html = render({ snapshot: SNAP, connected: true, receivedAt: Date.now(), events })
    expect(html).toContain('Live activity')
    expect(html).toContain('Patient Guide.docx')
    expect(html).toContain('Manual review requested')
    expect(html.match(/aria-live="polite"/g)).toHaveLength(1)
    expect(html).toContain('aria-label="Recent remediation activity"')
  })
})

describe('counters flash their increase like Discovery does', () => {
  it('routes known counts through the shared LiveCounter, not a second implementation', () => {
    const html = render({ snapshot: SNAP, connected: true, receivedAt: Date.now() })
    // LiveCounter's own markup. Asserting the class rather than the animation because the
    // count-up is rAF-driven and the "+N" is a CSS animation — neither is observable in a static
    // render, and liveCounter.test.jsx already covers the behaviour itself.
    expect(html).toContain('class="livecounter"')
  })

  it('keeps an unknown counter out of the animation entirely', () => {
    // "—" must not count up from zero, and a decrease must never flash green: LiveCounter
    // already refuses the second, and the em-dash branch is what keeps it clear of the first.
    const partial = { ...SNAP, documents: { ...SNAP.documents, waiting: null } }
    const html = render({ snapshot: partial, connected: true, receivedAt: Date.now() })
    const open = html.indexOf('data-testid="rem-count-waiting"')
    const cell = html.slice(html.indexOf('>', open) + 1, html.indexOf('</dd>', open))
    expect(cell).toBe('—')
    expect(cell).not.toContain('livecounter')
  })
})

describe('the v2 live operations hierarchy', () => {
  it('adds focusable segment details, retry timing, activity density, and documents in their phases', () => {
    const snapshot = { ...SNAP, retry_at: '2026-09-05T12:00:14Z', active_attempts: [
      { file: 'Patient Guide.docx', phase: 're-verifying the corrected copy', elapsed_s: 8, attempt: 2,
        trail: [{ label: '4 fixes applied' }] },
    ] }
    const html = render({ snapshot, connected: true, receivedAt: Date.now(), events: [
      { key: '17', tone: 'success', occurredAt: '2026-09-05T11:59:58Z', line: 'Verified Patient Guide.docx' },
    ] })
    expect(html).toContain('data-detail="Completed: 4"')
    expect(html).toContain('tabindex="0"')
    expect(html).toContain('Temporary issue')
    expect(html).toContain('Last 60 seconds')
    expect(html).toContain('remops-pipeline-moving')
    expect(html).toContain('Patient Guide.docx')
    expect(html).toContain('4 fixes applied')
  })

  it('renders reconciled progress before pipeline, active work, throughput, activity, and exceptions', () => {
    const html = render({ snapshot: { ...SNAP, active_attempts: [
      { file: 'guide.docx', phase: 're-verifying', elapsed_s: 8, attempt: 1 },
    ] }, connected: true, receivedAt: Date.now(), events: [
      { key: '17', kind: 'remediate.delivered', tone: 'success',
        occurredAt: '2026-09-05T12:00:00Z', line: 'Corrected copy delivered for guide.docx' },
    ] })
    const labels = ['documents complete', 'Active document pipeline', 'In flight now',
      'Throughput', 'Live activity', 'Needs attention']
    const positions = labels.map((label) => html.indexOf(label))
    expect(positions.every((position) => position >= 0)).toBe(true)
    expect(positions).toEqual([...positions].sort((a, b) => a - b))
    expect(html).toContain('Corrected copy delivered')
  })

  it('provides a motion-only pause without changing transport props', () => {
    const html = render({ snapshot: SNAP, connected: true, receivedAt: Date.now() })
    expect(html).toContain('Pause visual updates')
    expect(html).toContain('aria-pressed="false"')
    const source = readFileSync(join(here, 'RemediationOpsPanel.jsx'), 'utf8')
    expect(source).toContain('remops-motion-paused')
    expect(source).not.toMatch(/close\(|AbortController|openRemediationStream/)
  })

  it('labels polling fallback and never animates waiting, review, failed, or skipped counts', () => {
    const html = render({ snapshot: SNAP, connected: false, receivedAt: Date.now(), updateMode: 'polling' })
    expect(html).toContain('Updating by polling')
    for (const key of ['waiting', 'review', 'failed', 'skipped']) {
      const open = html.indexOf(`data-testid="rem-count-${key}"`)
      const cell = html.slice(html.indexOf('>', open) + 1, html.indexOf('</dd>', open))
      expect(cell).not.toContain('livecounter')
    }
  })
})

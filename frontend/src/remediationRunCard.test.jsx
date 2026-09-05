import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import RemediationRunCard from './RemediationRunCard.jsx'
import { progressBar, etaGate, runHeadline, shouldShowCard, SEGMENTS,
         MIN_DOCUMENTS_FOR_ETA } from './remediationRunCard.js'

const here = dirname(fileURLToPath(import.meta.url))

// The persistent run card. The properties worth pinning are the ones a plausible-looking card
// gets wrong: claiming a run is complete while its corrected copies are still being delivered,
// showing an ETA off four polls that finished nothing, and encoding state in colour alone.

const SNAP = {
  run_id: 'scan-1', scan_id: 'scan-1', revision: 1757068800000,
  state: 'running', message: 'Remediation in progress', terminal: false,
  source: { provider: 'sharepoint', provider_label: 'SharePoint',
            breadcrumb: 'SharePoint · Legal · Contracts', scan_snapshot_id: 'scan-1' },
  total_documents: 20,
  documents: { completed: 8, processing: 3, waiting: 5, review: 2, failed: 1, skipped: 1 },
  fixes: { applied: 26, verified: 21, verification_failures: 5, documents_verified: 8 },
  delivery: { stored: 8, delivered: 7, pending: 1, eligible: 8, latest_at: null },
  review: { documents: 2, items: 3 },
  phases: [
    { key: 'preparing', label: 'Preparing', status: 'completed', detail: null },
    { key: 'applying', label: 'Applying approved fixes', status: 'active', detail: null },
    { key: 'rechecking', label: 'Re-checking corrected documents', status: 'active', detail: null },
    { key: 'saving', label: 'Saving corrected copies', status: 'pending', detail: null },
    { key: 'finalizing', label: 'Finalizing evidence', status: 'pending', detail: null },
  ],
  thresholds: { stall_after_s: 900, heartbeat_s: 15, delayed_after_s: 60 },
  integrity: { ok: true, violations: [], affected: [] },
}

const render = (props) => renderToStaticMarkup(createElement(RemediationRunCard, props))

describe('the run card never overstates the run', () => {
  it('does not say Complete while corrected copies are still being delivered', () => {
    // The brief's rule. It holds because the SERVER has a distinct `completing` state for exactly
    // this — all documents terminal, delivery outstanding — and no mapping here can turn that
    // into "Complete".
    const completing = { ...SNAP, state: 'completing', terminal: false,
                         documents: { completed: 19, processing: 0, waiting: 0, review: 0,
                                      failed: 1, skipped: 0 },
                         delivery: { ...SNAP.delivery, delivered: 18, pending: 1 } }
    expect(runHeadline(completing).label).toBe('Finalizing')
    const html = render({ snapshot: completing, receivedAt: Date.now() })
    expect(html).toContain('Finalizing')
    expect(html).not.toMatch(/>Complete</)
  })

  it('withholds an ETA until five documents have completed, however many samples exist', () => {
    // The sample gate and the document gate answer different questions: four polls of a run that
    // finished nothing is four samples and no evidence.
    const calibrated = { calibrating: false, etaText: '8–12 minutes', ratePerMin: 6 }
    const few = { ...SNAP, documents: { ...SNAP.documents, completed: 4 } }
    expect(etaGate(few, calibrated)).toEqual({ show: false, note: 'Estimating after the first results' })
    const enough = { ...SNAP, documents: { ...SNAP.documents, completed: MIN_DOCUMENTS_FOR_ETA } }
    expect(etaGate(enough, calibrated)).toMatchObject({ show: true, text: '8–12 minutes' })
    // ...and a document count alone is not enough either — the measurement must have settled.
    expect(etaGate(enough, { calibrating: true, etaText: null }).show).toBe(false)
  })

  it('renders nothing at all before a run exists', () => {
    expect(shouldShowCard(null)).toBe(false)
    expect(shouldShowCard({ state: 'draft' })).toBe(false)
    expect(render({ snapshot: null })).toBe('')
    expect(render({ snapshot: { ...SNAP, state: 'draft' } })).toBe('')
  })
})

describe('the stacked bar is truthful about the scope', () => {
  it('partitions the scope and leaves waiting as the unfilled remainder', () => {
    const bar = progressBar(SNAP)
    expect(bar.total).toBe(20)
    expect(bar.segments.map((s) => [s.key, s.value])).toEqual([
      ['completed', 8], ['processing', 3], ['failed', 1], ['blocked', 3],   // review 2 + skipped 1
    ])
    expect(bar.waiting).toBe(5)
    // Every band plus the remainder accounts for the whole scope — the bar cannot show a run
    // shorter than it is.
    const filled = bar.segments.reduce((a, s) => a + s.value, 0)
    expect(filled + bar.waiting).toBe(bar.total)
  })

  it('draws nothing rather than a short bar when a counter is unknown', () => {
    expect(progressBar({ ...SNAP, documents: { ...SNAP.documents, review: null } })).toBe(null)
    expect(progressBar({ ...SNAP, total_documents: null })).toBe(null)
    expect(progressBar({})).toBe(null)
  })

  it('clamps the remainder at zero when counters exceed the scope', () => {
    // The counters disagreeing with the scope is an integrity violation the snapshot reports;
    // the bar must not render the disagreement as a negative-width shape.
    const over = { ...SNAP, total_documents: 5 }
    expect(progressBar(over).waiting).toBe(0)
    expect(progressBar(over).waitingPct).toBe(0)
  })
})

describe('state is never carried by colour alone', () => {
  it('labels every band with its name and count', () => {
    const html = render({ snapshot: SNAP, receivedAt: Date.now() })
    for (const word of ['completed', 'active', 'failed', 'blocked', 'waiting']) {
      expect(html).toContain(word)
    }
  })

  it('keeps the two confusable status hues non-adjacent in the fill order', () => {
    // THE ORDER IS THE ACCESSIBILITY FIX, so it is asserted rather than left to a comment.
    // The dataviz palette checker reports blue↔violet at ΔE 1.4 under protanopia — a protanope
    // cannot tell "active" from "blocked". Red between them lifts the worst adjacent pair to
    // ΔE 19.5. Reordering these keys silently re-breaks that.
    expect(SEGMENTS.map((s) => s.key)).toEqual(['completed', 'processing', 'failed', 'blocked'])
    expect(SEGMENTS.map((s) => s.fill)).toEqual(['#3B6D11', '#1F5FA8', '#B43A2A', '#7B4EA8'])
  })

  it('gives the bar a text alternative naming every count', () => {
    const html = render({ snapshot: SNAP, receivedAt: Date.now() })
    expect(html).toMatch(/aria-label="20 documents: 8 completed, 3 active, 1 failed, 3 blocked, 5 waiting"/)
  })

  it('announces the state, not the counters', () => {
    const html = render({ snapshot: SNAP, receivedAt: Date.now() })
    const live = html.match(/aria-live="polite"[^>]*>([^<]*)</)
    expect(live[1]).toContain('Applying fixes')
    expect(live[1]).not.toMatch(/\d/)      // no counter rides the announcement
  })
})

describe('freshness is reported honestly while polling', () => {
  it('does not claim Live when no stream is connected', () => {
    // useRemediationRun polls; it must not borrow the word that means "a stream is open".
    const html = render({ snapshot: SNAP, receivedAt: Date.now(), connected: false })
    expect(html).toContain('Reconnecting')
    expect(html).not.toContain('>Live<')
  })

  it('shows how old the last confirmed update is', () => {
    const html = render({ snapshot: SNAP, receivedAt: Date.now() - 30_000, connected: false })
    expect(html).toMatch(/updated 30s ago/)
  })
})

describe('the card outlives a tab change', () => {
  it('is mounted outside the tab panel, so a tab change cannot unmount it', () => {
    // THE WHOLE POINT OF THE COMPONENT. `<Remediate/>` renders only while view === 'remediate',
    // so a card inside the panel — or state owned by that component — dies on every tab change.
    // Asserted on App.jsx's structure because no unit render can observe a remount.
    const app = readFileSync(join(here, 'App.jsx'), 'utf8')
    const card = app.indexOf('<RemediationRunCard')
    const panel = app.indexOf('id="workflow-panel"')
    expect(card).toBeGreaterThan(-1)
    expect(panel).toBeGreaterThan(-1)
    expect(card).toBeLessThan(panel)
  })

  it('calls the hook unconditionally, above the sign-in early return', () => {
    // BOTH HALVES OF THIS BROKE THE WHOLE APP once, and neither was visible to any test of the
    // card itself — the full suite caught them:
    //   · reading the `run` const (derived far below) is a temporal-dead-zone ReferenceError,
    //   · a hook placed after `if (!me) return <SignIn/>` runs on some renders and not others,
    //     which React rejects with "Rendered more hooks than during the previous render".
    // So the call must read `scan?.run?.id` and must sit above that return.
    const app = readFileSync(join(here, 'App.jsx'), 'utf8')
    const call = app.indexOf('useRemediationRun(scan?.run?.id')
    expect(call).toBeGreaterThan(-1)
    // Match the RETURN STATEMENT, not the words — App.jsx discusses this early return in prose
    // above it, and an indexOf on the sentence finds the comment first. That mistake made an
    // earlier version of this check report a correct placement as wrong.
    const earlyReturn = app.search(/^ {2}if \(!me\) return <SignIn/m)
    expect(earlyReturn).toBeGreaterThan(-1)
    expect(call).toBeLessThan(earlyReturn)
  })

  it('tears down both the poll and the stream when it unmounts', () => {
    // Now that the hook owns the connection as well as the poll, unmounting has to close BOTH —
    // a stream left open by a torn-down hook is a socket nothing will ever read from again.
    const hook = readFileSync(join(here, 'useRemediationRun.js'), 'utf8')
    const cleanup = hook.slice(hook.lastIndexOf('return () => {'))
    expect(cleanup).toContain('live = false')
    expect(cleanup).toContain('stopPoll()')
    expect(cleanup).toContain('streamRef.current?.close?.()')
  })

  it('never lets an older snapshot overwrite newer progress', () => {
    // A superseded read arriving late would walk the counters backwards, which reads as the run
    // regressing. The guard is isNewer, shared with the ops panel.
    const hook = readFileSync(join(here, 'useRemediationRun.js'), 'utf8')
    expect(hook).toContain('isNewer')
    expect(hook).toContain('if (!isNewer(snapRef.current, next)) return')
  })

  it('clears the previous run before showing the next', () => {
    const hook = readFileSync(join(here, 'useRemediationRun.js'), 'utf8')
    const effect = hook.slice(hook.indexOf('useEffect'))
    expect(effect.indexOf('setSnapshot(null)')).toBeLessThan(effect.indexOf('if (!runId)'))
  })
})

describe('corrected copies and verified documents stay distinct', () => {
  it('shows delivery and verification as separate, unit-named numbers', () => {
    const html = render({ snapshot: SNAP, receivedAt: Date.now() })
    expect(html).toContain('Fixes applied')
    expect(html).toContain('Fixes verified')
    expect(html).toContain('Corrected copies delivered')
    expect(html).toContain('Pending delivery')
    // Never a bare, unit-less "Verified" — it was read as documents on one line and fixes on the
    // next, from the same number.
    expect(html).not.toMatch(/>Verified</)
  })
})

describe('one stream, owned above the tab switch', () => {
  const hook = () => readFileSync(join(here, 'useRemediationRun.js'), 'utf8')
  const remediate = () => readFileSync(join(here, 'Remediate.jsx'), 'utf8')

  it('is opened in exactly one place', () => {
    // Two openers would put two SSE connections on one run — the thing moving ownership was for.
    // Remediate consumes frames through the `runStream` prop instead.
    expect(hook()).toMatch(/openRemediationStream\(runId/)
    expect(remediate()).not.toMatch(/openRemediationStream\(/)
  })

  it('keeps the resume cursor in the hook, so it survives a tab change', () => {
    // THIS IS WHAT THE MOVE BUYS. ADR 0051's resume replays the events a browser missed, keyed on
    // the last id it rendered. While that cursor lived in Remediate's ref it died with the
    // component — so every tab change threw it away and the reconnect replayed nothing, which is
    // the one case resume was built for. In the hook it outlives the unmount.
    expect(hook()).toContain('cursorRef')
    expect(hook()).toMatch(/lastEventId: cursorRef\.current/)
    expect(remediate()).not.toContain('eventCursorRef')
  })

  it('never carries a cursor from one run into another', () => {
    // A cursor from run A points at a position in A's log. Sent for run B the server correctly
    // refuses it as ahead of the log — a reconcile on every first connect, forever.
    const effect = hook().slice(hook().indexOf('useEffect'))
    expect(effect.indexOf('cursorRef.current = null')).toBeLessThan(effect.indexOf('if (!runId)'))
  })

  it('advances the cursor only from the frame id, never from the payload', () => {
    expect(hook()).toMatch(/onEvent: \(event, id\) => \{/)
    expect(hook()).toMatch(/if \(id != null\) cursorRef\.current = id/)
    expect(hook()).toMatch(/addRemediationEvent\(previous, event, id\)/)
  })

  it('drops a rejected cursor and re-fetches rather than retrying it forever', () => {
    const reconcile = hook().slice(hook().indexOf('onReconcile:'))
    expect(reconcile.slice(0, 400)).toContain('cursorRef.current = null')
    expect(reconcile.slice(0, 400)).toContain('loadSnapshot()')
  })

  it('polls only while nothing is streaming', () => {
    // The poll is the FALLBACK. A live frame supersedes it, and the stream closing (which happens
    // when the batch drains, not when the run finishes) turns it back on so the card keeps
    // reconciling review, delivery and evidence.
    const h = hook()
    expect(h).toMatch(/stopPoll\(\)\s+\/\/ a live frame supersedes the fallback/)
    const onDone = h.slice(h.indexOf('onDone:'))
    expect(onDone.slice(0, 600)).toContain('startPoll()')
  })

  it('does not finalize a fresh batch on a previous run\'s stream close', () => {
    // `endedAt` is a timestamp, not a flag, precisely so "the stream ended" for run A cannot be
    // mistaken for run B's completion by a component that started watching afterwards.
    expect(hook()).toContain('setEndedAt(Date.now())')
    expect(remediate()).toContain('endedSeenRef.current = runStream?.endedAt || 0')
    expect(remediate()).toMatch(/if \(!ended \|\| ended === endedSeenRef\.current \|\| !total\) return/)
  })
})

import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import AssessRunProgress from './AssessRunProgress.jsx'

// The Assess RUNNING screen (board assess-03): a per-document focus card, NOT a mid-run scoreboard.
// The rule it enforces is that no verdict-shaped count renders while the run is in flight — those
// live on the Overview now, where they read as a result. This screen says which document is being
// worked, how far through the estate we are, and that the results arrive at the end.

const SNAP = {
  available: true, active: true, phase: 'assessing', run_id: 's1',
  totals: { discovered: 22, eligible: 22 },
  kpis: { completed: 8, need_attention: 3, unable_to_assess: 1, processing: 1 },
  queue: {
    current: { file: 'Finance/Q3 Board Pack.pdf', criterion: '1.1.1',
               criterion_name: 'Non-text content', action: 'Describing 6 images that have no alt text' },
    in_flight: 1, queued: 13, workers: { busy: 1, max: 4 },
  },
}
const render = (snapshot, throughput, onStop) =>
  renderToStaticMarkup(createElement(AssessRunProgress, { snapshot, throughput, onStop }))

describe('the assessment running screen focuses on the document in flight', () => {
  it('renders nothing until the live snapshot is available', () => {
    expect(render(null)).toBe('')
    expect(render({ available: false })).toBe('')
  })

  it('names the estate size and the document being worked, 1-based', () => {
    const html = render(SNAP, { etaText: 'about 1 min 50s left' })
    expect(html).toContain('Assessing 22 documents')
    // 8 completed → the 9th is in flight.
    expect(html).toContain('Document 9 of 22')
    expect(html).toContain('Finance/Q3 Board Pack.pdf')
    expect(html).toContain('Describing 6 images that have no alt text')
    expect(html).toContain('about 1 min 50s left')
    expect(html).toMatch(/Results appear when the run finishes/)
  })

  it('never renders a mid-run verdict scoreboard', () => {
    // The whole point of board 3: no partially-filled count of failures. The snapshot carries
    // need_attention / unable_to_assess KPIs; this screen must not surface them as counts.
    const html = render(SNAP)
    expect(html, 'a need-attention verdict leaked onto the running screen').not.toMatch(/[Nn]eed.attention/)
    expect(html, 'an unable-to-assess verdict leaked onto the running screen').not.toMatch(/[Uu]nable to assess/)
    // No standalone "3" / "1" verdict counts from the KPI block — the only counts are the document
    // position and the estate size.
    expect(html).not.toMatch(/<b[^>]*>3<\/b>/)
  })

  it('clamps the position so the last frame never reads "23 of 22"', () => {
    const last = { ...SNAP, kpis: { ...SNAP.kpis, completed: 22 } }
    expect(render(last)).toContain('Document 22 of 22')
  })

  it('falls back to the lane label when no document is currently reported', () => {
    const idle = { ...SNAP, queue: { ...SNAP.queue, current: null, in_flight: 0 } }
    const html = render(idle)
    expect(html).toContain('Assessing 22 documents')
    expect(html).toContain('Idle')
  })
})

describe('Stop — board-exact placement, inline with what stopping does', () => {
  it('offers Stop only when both an active run and a handler are given', () => {
    expect(render(SNAP, undefined, () => {})).toContain('>Stop<')
    expect(render(SNAP, undefined, undefined), 'Stop rendered with no handler to call').not.toContain('>Stop<')
    const notActive = { ...SNAP, active: false }
    expect(render(notActive, undefined, () => {}), 'Stop offered on a run with nothing left to stop')
      .not.toContain('>Stop<')
  })

  it('sits beside the explanation of what stopping does, not alone', () => {
    const html = render(SNAP, undefined, () => {})
    const stopAt = html.indexOf('>Stop<')
    const explainAt = html.indexOf('Results appear when the run finishes')
    expect(stopAt).toBeGreaterThan(-1)
    expect(explainAt).toBeGreaterThan(-1)
    // Same flex row — within a couple hundred characters of markup, not on a separate row far away.
    expect(explainAt - stopAt).toBeLessThan(400)
  })
})

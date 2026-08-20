import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import LiveAssessment from './LiveAssessment.jsx'

afterEach(unmountAll)

const SNAP = {
  available: true, active: true, phase: 'assessing',
  totals: { discovered: 819, eligible: 512 },
  kpis: { completed: 145, processing: 105, need_attention: 22, unable_to_assess: 3 },
  queue: {
    in_flight: 6, queued: 99, workers: { busy: 6, max: 8, idle: 2 },
    current: { file: 'discharge.pdf', criterion: '1.4.3', text: 'Assessing discharge.pdf for 1.4.3  (+5 more in progress)' },
    processing: true, stale: false,
  },
  kpis_pending: [],
}

function render(props) {
  const { container, root } = createTestRoot()
  act(() => root.render(createElement(LiveAssessment, props)))
  return container
}

describe('LiveAssessment', () => {
  it('renders the KPI values, the discovered/assessable line, and the live worker lane', () => {
    const t = render({ snapshot: SNAP }).textContent
    expect(t).toMatch(/Assessing/)
    expect(t).toMatch(/819 discovered/)
    expect(t).toMatch(/512 assessable/)
    expect(t).toMatch(/145/)                          // completed
    expect(t).toMatch(/6.*in.?flight/i)
    expect(t).toMatch(/99.*queued/i)
    expect(t).toMatch(/6 \/ 8 workers busy/)
    expect(t).toMatch(/discharge\.pdf/)               // the current lane
  })

  it('shows "coming online" when the queue block is not present yet (older backend)', () => {
    const t = render({ snapshot: { ...SNAP, queue: undefined, kpis_pending: ['queue'] } }).textContent
    expect(t).toMatch(/coming online/i)
    expect(t).not.toMatch(/in.?flight/i)              // no fabricated zero worker row
  })

  it('a stale queue reads as paused, not busy', () => {
    const t = render({ snapshot: { ...SNAP, queue: { ...SNAP.queue, stale: true } } }).textContent
    expect(t).toMatch(/paused/i)
    expect(t).not.toMatch(/discharge\.pdf/)           // frozen current is cleared
  })

  it('renders nothing when there is no active/available snapshot', () => {
    expect(render({ snapshot: { available: false } }).textContent).toBe('')
    expect(render({ snapshot: null }).textContent).toBe('')
  })
})

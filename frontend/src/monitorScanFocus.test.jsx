import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// Stakeholder UX review, 2026-08-30: "View in Monitor →" (Discover's DiscoverQueueCard /
// ProcessingStatusPanel, and AssessRunner's own ProcessingStatusPanel) used to just
// `setView('monitor')` — landing on Monitor's unfiltered queue with no indication which scan the
// click was even about. This wires a `monitorFocusScanId` through App.jsx -> Monitor -> QueuePanel
// so the click highlights the originating run instead.
//
// "Highlight, do not hide" (see CLAUDE.md's retired-features section for the general
// never-hide-only-surface convention): every job stays in the "Recent jobs" list, the focused
// scan's own job(s) just carry a distinct border/background and a dismissible banner.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

// ── App.jsx wiring — source-level, matching monitorQueuePreGate.test.jsx's established pattern
// for this exact tradeoff (mounting the real App.jsx means stubbing its whole dependency graph
// just to reach two call sites, for a check a static read answers directly and more legibly). ──

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')
const code = (f) => read(f)
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')

describe('Monitor scan focus — App.jsx wiring', () => {
  const app = () => code('App.jsx')

  it('declares monitorFocusScanId state, defaulting to no focus', () => {
    expect(app()).toMatch(/const \[monitorFocusScanId, setMonitorFocusScanId\] = useState\(null\)/)
  })

  it("Discover's onViewMonitor sets the focus id (the live/just-started scan) before switching view", () => {
    expect(app()).toMatch(
      /onViewMonitor=\{\(\) => \{ setMonitorFocusScanId\(liveScanId \|\| run\?\.id\); setView\('monitor'\) \}\}/)
  })

  it("AssessRunner's onViewMonitor sets the focus id (the run being assessed) before switching view", () => {
    expect(app()).toMatch(
      /onViewMonitor=\{\(\) => \{ setMonitorFocusScanId\(run\.id\); setView\('monitor'\) \}\}/)
  })

  it('AssessRunner actually receives onViewMonitor from its App.jsx mount site', () => {
    // The task brief flagged this as unconfirmed — AssessRunner.jsx destructures the prop and
    // passes it into ProcessingStatusPanel, but that's dead unless the mount site hands it one.
    const m = app().match(/<AssessRunner key=\{run\.id\}[^]*?\/>/)
    expect(m, 'the AssessRunner mount was not found in the shape this test expects').toBeTruthy()
    expect(m[0]).toMatch(/onViewMonitor=/)
  })

  it('passes focusScanId + onClearFocus into <Monitor> (the assessed branch)', () => {
    const m = app().match(/assessed \? (<Monitor [^]*?\/>) : /)
    expect(m, "the monitor tab's assessed branch wasn't found in the shape this test expects").toBeTruthy()
    expect(m[1]).toMatch(/focusScanId=\{monitorFocusScanId\}/)
    expect(m[1]).toMatch(/onClearFocus=\{\(\) => setMonitorFocusScanId\(null\)\}/)
  })

  it('passes focusScanId + onClearFocus into the not-yet-assessed <QueuePanel> too', () => {
    const m = app().match(/\{view === 'monitor' && \(run \? \(assessed \? <Monitor [^]*?\/> : <>(<QueuePanel[^]*?\/>)\{assessGate\}<\/>\) : /)
    expect(m, "the monitor tab's not-yet-assessed branch wasn't found in the shape this test expects").toBeTruthy()
    expect(m[1]).toMatch(/focusScanId=\{monitorFocusScanId\}/)
    expect(m[1]).toMatch(/onClearFocus=\{\(\) => setMonitorFocusScanId\(null\)\}/)
  })
})

// ── QueuePanel — full DOM mount, matching queuePanelCapacity.test.jsx / queuePanelDiagnosis.
// test.jsx's own conventions for mocking ./api.js and mounting. ──

const getJobs = vi.fn()
vi.mock('./api.js', () => ({
  getJobs: (...a) => getJobs(...a),
  setWorkers: vi.fn(),
  clearDeadJobs: vi.fn(),
  getWorkerReplicas: vi.fn().mockResolvedValue({ configured: false, min_replicas: null, max_replicas: null }),
  setWorkerReplicas: vi.fn(),
  getWorkerCapacity: vi.fn().mockResolvedValue({ configured: false, current_replicas: null, cpu_percent: null,
                                                 memory_percent: null, metrics_available: false }),
  // Every sample job below carries a scan_id, so TraceChip (Transparency.jsx) renders and calls
  // this — unmocked, it throws "no openTraceUrl export" and fails every test in this file.
  openTraceUrl: vi.fn(() => null),
}))

// jobsFeed.js shares ONE GET /jobs subscription across every component that wants it, and keeps
// its cached payload across unmount on purpose: a remount seconds later should draw immediately,
// and the payload carries its real fetchedAt plus a `stale` flag so it cannot pass as fresh.
// Within a test file that means one test's cache would otherwise answer the next test's mock.
// Reset it explicitly here — the module's production behaviour is deliberate and is covered in
// jobsFeed.test.js; it is this file that needs a cold start, not the cache that needs weakening.
import { resetJobsFeed } from './jobsFeed.js'
beforeEach(() => { resetJobsFeed() })


const { default: QueuePanel } = await import('./QueuePanel.jsx')

let container, root
const mount = async (props = {}) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(QueuePanel, props)) })
  await settle()
  return container
}
const settle = async (n = 4) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }

afterEach(() => { unmountAll(); getJobs.mockReset() })

const t0 = new Date().toISOString()
const job = (id, scan_id, status = 'done') => ({
  id, type: 'scan_file', status, scan_id, payload: JSON.stringify({ file: `${id}.docx` }),
  created_at: t0, updated_at: t0,
})

describe('QueuePanel scan focus', () => {
  it('highlights only the job card(s) matching focusScanId', async () => {
    getJobs.mockResolvedValue({
      workers: 2, worker_tier_alive: true, runtime_mode: 'auto', stats: {},
      jobs: [job('j1', 'scan-A'), job('j2', 'scan-B'), job('j3', 'scan-A')],
    })
    const c = await mount({ focusScanId: 'scan-A' })
    const cards = c.querySelectorAll('.jobcard')
    expect(cards.length).toBe(3)
    const focused = c.querySelectorAll('.jobcard.focused')
    expect(focused.length).toBe(2)
    focused.forEach((card) => expect(card.textContent).toMatch(/j1|j3/))
  })

  it('shows the dismissible "Focused on this run" banner when focused', async () => {
    getJobs.mockResolvedValue({
      workers: 2, worker_tier_alive: true, runtime_mode: 'auto', stats: {},
      jobs: [job('j1', 'scan-A')],
    })
    const c = await mount({ focusScanId: 'scan-A' })
    expect(c.textContent).toMatch(/Focused on this run/)
    expect(c.textContent).toMatch(/Show all/)
  })

  it('renders normally — no highlight, no banner — when focusScanId is null (ordinary Monitor-tab click)', async () => {
    getJobs.mockResolvedValue({
      workers: 2, worker_tier_alive: true, runtime_mode: 'auto', stats: {},
      jobs: [job('j1', 'scan-A'), job('j2', 'scan-B')],
    })
    const c = await mount()
    expect(c.querySelectorAll('.jobcard.focused').length).toBe(0)
    expect(c.textContent).not.toMatch(/Focused on this run/)
  })

  it('"Show all" calls onClearFocus to clear the focus', async () => {
    getJobs.mockResolvedValue({
      workers: 2, worker_tier_alive: true, runtime_mode: 'auto', stats: {},
      jobs: [job('j1', 'scan-A')],
    })
    const onClearFocus = vi.fn()
    const c = await mount({ focusScanId: 'scan-A', onClearFocus })
    const btn = Array.from(c.querySelectorAll('button')).find((b) => b.textContent === 'Show all')
    expect(btn).toBeTruthy()
    await act(async () => { btn.click() })
    expect(onClearFocus).toHaveBeenCalledTimes(1)
  })

  it('never drops a job from the list to build the highlight — highlight, not filter', async () => {
    getJobs.mockResolvedValue({
      workers: 2, worker_tier_alive: true, runtime_mode: 'auto', stats: {},
      jobs: [job('j1', 'scan-A'), job('j2', 'scan-B'), job('j3', 'scan-C')],
    })
    const c = await mount({ focusScanId: 'scan-A' })
    expect(c.querySelectorAll('.jobcard').length).toBe(3)
    expect(c.textContent).toMatch(/j2\.docx/)
    expect(c.textContent).toMatch(/j3\.docx/)
  })

  it('surfaces the focused job when it has already been pushed off the visible top 8', async () => {
    // 8 recent jobs from OTHER scans, then a 9th (oldest, already terminal) that belongs to the
    // focused scan — a real case (an old done/dead job pushed out by newer activity), not one to
    // silently drop the highlight for.
    const recent = Array.from({ length: 8 }, (_, i) => job(`r${i}`, 'scan-other', 'done'))
    const old = job('old1', 'scan-focused', 'dead')
    getJobs.mockResolvedValue({
      workers: 2, worker_tier_alive: true, runtime_mode: 'auto', stats: {},
      jobs: [...recent, old],
    })
    const c = await mount({ focusScanId: 'scan-focused' })
    // All 8 visible cards remain, PLUS the surfaced one — nothing was dropped to make room.
    expect(c.querySelectorAll('.jobcard').length).toBe(9)
    expect(c.querySelectorAll('.jobcard.focused').length).toBe(1)
    expect(c.textContent).toMatch(/not in the most recent 8/)
  })

  it('does not surface anything extra when the focused scan has no job in the queue at all', async () => {
    getJobs.mockResolvedValue({
      workers: 2, worker_tier_alive: true, runtime_mode: 'auto', stats: {},
      jobs: [job('j1', 'scan-B'), job('j2', 'scan-C')],
    })
    const c = await mount({ focusScanId: 'scan-nowhere' })
    expect(c.querySelectorAll('.jobcard').length).toBe(2)
    expect(c.querySelectorAll('.jobcard.focused').length).toBe(0)
    // The banner still shows (the focus itself is real and dismissible), it just has nothing to
    // highlight — matches finding zero rows for a filter, not an error state.
    expect(c.textContent).toMatch(/Focused on this run/)
  })
})

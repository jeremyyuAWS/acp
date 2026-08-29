/**
 * ADR 0042 · Run history — the durable lifecycle log of one run, rendered.
 *
 * The fixtures are the shapes `store.list_scan_events` actually returns (see the emit sites in
 * api/handlers.py), so these test the real record rather than a convenient one. The assertions
 * concentrate on the three places this panel could quietly mislead:
 *
 *   1. AN EMPTY LIST AND A FAILED READ ARE DIFFERENT SENTENCES. "No history recorded" is a true
 *      statement about pre-ADR runs; it must never be shown when the request simply failed.
 *   2. RETRIES AND SECOND WORKERS MUST STAY VISIBLE. The log is append-only precisely so a
 *      reclaimed run's two `scan.claimed` rows both survive; a panel that de-duplicated them
 *      would erase the evidence the log exists to keep.
 *   3. THE OUTCOME IS THE FIRST TERMINAL EVENT, not the last row — ADR 0042's read rule, which is
 *      what makes a duplicate terminal event from a re-delivered job harmless.
 *
 * DOM-level, not browser-level: vite serves the SHARED checkout whatever worktree you are in
 * (CLAUDE.md), so a browser check would exercise code without this.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const getScanHistory = vi.fn()
vi.mock('./api.js', () => ({ getScanHistory: (...a) => getScanHistory(...a) }))

const { normalizeEvent, normalizeHistory, KIND_LABEL } = await import('./scanHistory.js')
const ScanHistory = (await import('./ScanHistory.jsx')).default

afterEach(unmountAll)
beforeEach(() => {
  getScanHistory.mockReset()
  getScanHistory.mockResolvedValue({ available: true, events: [], count: 0, latest_seq: null })
})

const ev = (seq, kind, extra = {}) => ({
  event_id: `e${seq}`, scan_id: 's1', seq, kind,
  occurred_at: `2026-08-29T09:0${seq}:00+00:00`, phase: null, job_id: 'j1',
  worker_id: null, attempt: 1, detail: null, owner_email: 'demo', ...extra,
})

const CLEAN_RUN = [
  ev(1, 'scan.queued', { detail: { source: 'drive', job_type: 'scan_discover' } }),
  ev(2, 'scan.claimed', { worker_id: 'w3' }),
  ev(3, 'scan.listing_started'),
  ev(4, 'scan.listing_complete', { detail: { files_found: 4100, truncated: false } }),
  ev(5, 'scan.inventory_saved', { detail: { new: 4100, updated: 0, failed: 0 } }),
  ev(6, 'scan.lifecycle_applied', { detail: { rules_enabled: 2, matches: 11 } }),
  ev(7, 'scan.discovered', { detail: { files_found: 4100, source: 'drive' } }),
]

const body = (events) => ({ available: true, scan_id: 's1', events,
                            count: events.length,
                            latest_seq: events.length ? events[events.length - 1].seq : null })

async function mount(props = { scanId: 's1' }) {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(ScanHistory, props)) })
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
  return { container, root }
}

async function open(container) {
  const btn = container.querySelector('button[aria-expanded]')
  await act(async () => { btn.click() })
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
  return container
}

// ── the normalizer ───────────────────────────────────────────────────────────

describe('normalizeHistory', () => {
  it('reads the outcome as the FIRST terminal event, not the last row', () => {
    // A re-delivered discover job appends a second scan.discovered. ADR 0042's rule is that the
    // first terminal event wins; without it a duplicate would silently redefine the outcome.
    const m = normalizeHistory(body([...CLEAN_RUN, ev(8, 'scan.discovered')]))
    expect(m.outcome.seq).toBe(7)
  })

  it('counts retries and distinct workers so a reclaimed run is legible', () => {
    const m = normalizeHistory(body([
      ev(1, 'scan.claimed', { worker_id: 'w1' }),
      ev(2, 'scan.retrying', { attempt: 2, detail: { error_class: 'rate_limit' } }),
      ev(3, 'scan.claimed', { worker_id: 'w2', attempt: 2 }),
      ev(4, 'scan.discovered'),
    ]))
    expect(m.retries).toBe(1)
    expect(m.workers).toEqual(['w1', 'w2'])
    expect(m.events).toHaveLength(4)  // both claims survive — nothing is de-duplicated
  })

  it('treats an unavailable body as unavailable, not as an empty run', () => {
    const m = normalizeHistory({ available: false, reason: 'scan_not_found' })
    expect(m.available).toBe(false)
    expect(m.events).toEqual([])
  })

  it('is total on junk', () => {
    for (const junk of [null, undefined, {}, { events: 'nope' }]) {
      expect(() => normalizeHistory(junk)).not.toThrow()
    }
    expect(normalizeHistory({ available: true, events: 'nope' }).events).toEqual([])
  })
})

describe('normalizeEvent', () => {
  it('withholds attempt 1 and surfaces a real retry attempt', () => {
    expect(normalizeEvent(ev(1, 'scan.claimed')).attempt).toBe(null)
    expect(normalizeEvent(ev(1, 'scan.claimed', { attempt: 3 })).attempt).toBe(3)
  })

  it('keeps false and 0 in the detail summary — they are real answers', () => {
    const e = normalizeEvent(ev(4, 'scan.listing_complete',
                                { detail: { files_found: 0, truncated: false } }))
    const shown = Object.fromEntries(e.fields.map((f) => [f.label, f.value]))
    expect(shown.files).toBe('0')
    expect(shown.truncated).toBe('no')
  })

  it('marks failure and retry distinctly, and a retry is not an outcome', () => {
    expect(normalizeEvent(ev(1, 'scan.failed')).severity).toBe('bad')
    expect(normalizeEvent(ev(1, 'scan.retrying')).severity).toBe('warn')
    expect(normalizeEvent(ev(1, 'scan.retrying')).isTerminal).toBe(false)
    expect(normalizeEvent(ev(1, 'scan.discovered')).severity).toBe('ok')
  })

  it('renders an unknown kind rather than dropping it', () => {
    const e = normalizeEvent(ev(1, 'scan.something_new'))
    expect(e.label).toBe('scan.something_new')
  })

  it('labels every kind the backend can emit', () => {
    // Mirrors Store.SCAN_EVENT_KINDS; a kind added there without a label here renders raw.
    for (const k of ['scan.queued', 'scan.claimed', 'scan.listing_started', 'scan.listing_complete',
                     'scan.inventory_saved', 'scan.lifecycle_applied', 'scan.discovered',
                     'scan.assess_started', 'scan.retrying', 'scan.paused', 'scan.resumed',
                     'scan.cancelled', 'scan.completed', 'scan.failed', 'scan.interrupted']) {
      expect(KIND_LABEL[k], `${k} has no label`).toBeTruthy()
    }
  })
})

// ── the component ────────────────────────────────────────────────────────────

describe('ScanHistory rendering', () => {
  it('is collapsed by default and does not fetch until opened', async () => {
    const { container } = await mount()
    expect(getScanHistory).not.toHaveBeenCalled()
    expect(container.querySelectorAll('.run-history-row')).toHaveLength(0)

    await open(container)
    expect(getScanHistory).toHaveBeenCalledWith('s1')
  })

  it('renders one row per event, oldest first', async () => {
    getScanHistory.mockResolvedValue(body(CLEAN_RUN))
    const container = await open((await mount()).container)

    const rows = [...container.querySelectorAll('.run-history-row')]
    expect(rows).toHaveLength(7)
    expect(rows.map((r) => r.dataset.kind)).toEqual(CLEAN_RUN.map((e) => e.kind))
    expect(container.textContent).toContain('Worker assigned')
    expect(container.textContent).toContain('4100')
  })

  it('says a failed READ is a failed read, never "no history"', async () => {
    getScanHistory.mockRejectedValue(new Error('network'))
    const container = await open((await mount()).container)

    expect(container.querySelector('.run-history-error')).toBeTruthy()
    expect(container.querySelector('.run-history-empty')).toBeFalsy()
    expect(container.textContent).toMatch(/does not mean nothing happened/i)
  })

  it('says a genuinely empty run is empty, and does not claim nothing happened', async () => {
    getScanHistory.mockResolvedValue(body([]))
    const container = await open((await mount()).container)

    expect(container.querySelector('.run-history-empty')).toBeTruthy()
    expect(container.querySelector('.run-history-error')).toBeFalsy()
    expect(container.textContent).toMatch(/not a statement that nothing happened/i)
  })

  it('surfaces a reclaimed run in the summary line', async () => {
    getScanHistory.mockResolvedValue(body([
      ev(1, 'scan.claimed', { worker_id: 'w1' }),
      ev(2, 'scan.retrying', { attempt: 2 }),
      ev(3, 'scan.claimed', { worker_id: 'w2', attempt: 2 }),
      ev(4, 'scan.discovered'),
    ]))
    const container = await open((await mount()).container)

    const summary = container.querySelector('.run-history-summary')
    expect(summary.textContent).toMatch(/Retried\s*1\s*time/)
    expect(summary.textContent).toMatch(/2\s*workers/)
    expect(container.querySelectorAll('[data-kind="scan.claimed"]')).toHaveLength(2)
  })

  it('shows no summary line for a clean run — nothing to explain', async () => {
    getScanHistory.mockResolvedValue(body(CLEAN_RUN))
    const container = await open((await mount()).container)
    expect(container.querySelector('.run-history-summary')).toBeFalsy()
  })

  it('renders nothing at all without a scanId', async () => {
    const { container } = await mount({ scanId: null })
    expect(container.querySelector('.run-history')).toBeFalsy()
    expect(getScanHistory).not.toHaveBeenCalled()
  })
})

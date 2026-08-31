/**
 * Assess's progress bar and its caption must count against the SAME total.
 *
 * The caption, the "Computing conformance · N documents" line and the no-workers banner all read
 * the server's own count — `run.files`, carried in state as `liveTotal` and documented at its
 * declaration as "the REAL total, not docs.length". The percentage alone does not:
 *
 *     const pct = Math.round((progress / Math.max(1, assessN, docs.length)) * 100)
 *
 * `progress` is `Math.min(scored.length, run.files)` — a SERVER-scale numerator. `assessN` and
 * `docs.length` are derived from the `files` PROP. Dividing one by the other divides two unrelated
 * scales, and `Math.max` does not reconcile them: it just picks the larger client number.
 *
 * On the deferred path (ADR 0020) the prop legitimately lags the server — Assess is running
 * precisely because the files have no scores yet — so this is the normal case, not an edge one. A
 * run over 148 documents with 12 scored renders a bar at 60% beside a caption reading "12 of
 * 148", which is 8%.
 *
 * The fix is to let the percentage read the same `liveTotal` every other consumer already does.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const assessScan = vi.fn()
const getScan = vi.fn()
const getQueueJob = vi.fn()
vi.mock('./api.js', () => ({
  assessScan: (...a) => assessScan(...a),
  getScan: (...a) => getScan(...a),
  getQueueJob: (...a) => getQueueJob(...a),
  getJobs: vi.fn(() => Promise.resolve({ workers: 4, worker_tier_alive: true,
                                         runtime_mode: 'in-process',
                                         stats: { running: 1, queued: 0, done: 0 },
                                         dead_letters: { by_type: {}, top_errors: [] }, jobs: [] })),
  setWorkers: vi.fn(() => Promise.resolve({ workers: 4 })),
  getCapability: vi.fn(() => Promise.resolve(null)),
  refreshScanDriveToken: vi.fn(() => Promise.resolve(null)),
  getScanTraces: vi.fn(() => Promise.resolve([])),
  getScanLive: vi.fn(() => Promise.resolve({ queue: null })),
  getWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
  setWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
  getQueueEstimate: vi.fn(() => Promise.resolve({ available: false })),
}))

import { resetJobsFeed } from './jobsFeed.js'
const { default: AssessRunner } = await import('./AssessRunner.jsx')

let container, root, errSpy
const mount = async (files) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(AssessRunner, { files, runId: 's1' })) })
}
const settle = async (n = 8) => {
  for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}
const clickText = async (t) => {
  const el = [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))
  await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
}
const text = () => container.textContent

/** The rendered bar width, as a number of percent. */
const barPct = () => {
  const bar = container.querySelector('.assessbar i') || container.querySelector('i[style*="width"]')
  if (!bar) return null
  const m = /([\d.]+)%/.exec(bar.getAttribute('style') || '')
  return m ? Number(m[1]) : null
}

const SERVER_TOTAL = 148
const SCORED = 12

/** The deferred shape: the server knows 148 files and has scored 12; the prop still lags. */
const DEFERRED_MIDRUN = {
  run: { files: SERVER_TOTAL },
  files: Array.from({ length: SERVER_TOTAL }, (_, i) => (
    i < SCORED
      ? { file: `f${i}.docx`, score: 90, status: 'done' }
      : { file: `f${i}.docx`, score: null, status: 'discovered' })),
}

/** What the component is handed while the scan is still deferred — no scores yet. */
const PROP_FILES = Array.from({ length: 20 }, (_, i) => (
  { file: `f${i}.docx`, score: null, status: 'discovered' }))

beforeEach(() => {
  resetJobsFeed()
  assessScan.mockReset(); getScan.mockReset(); getQueueJob.mockReset()
  errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  try { sessionStorage.clear() } catch { /* ignore */ }
})
afterEach(() => { errSpy.mockRestore(); unmountAll(); resetJobsFeed() })

describe('the progress bar and its caption share one denominator', () => {
  it('does not render a bar percentage that contradicts "N of M"', async () => {
    assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 4, worker_tier_alive: true })
    getScan.mockResolvedValue(DEFERRED_MIDRUN)
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'running', phase: 'assessing' })

    await mount(PROP_FILES)
    await clickText('Assess')
    await settle()

    expect(text()).toContain(`${SCORED} of ${SERVER_TOTAL}`)

    const expected = Math.round((SCORED / SERVER_TOTAL) * 100)   // 8
    const shown = barPct()
    expect(shown).not.toBeNull()
    expect(shown).toBe(expected)
  })

  it('agrees with the "Computing conformance · N documents" line', async () => {
    // That line already reads liveTotal. The bar must not disagree with a number on the same card.
    assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 4, worker_tier_alive: true })
    getScan.mockResolvedValue(DEFERRED_MIDRUN)
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'running', phase: 'assessing' })

    await mount(PROP_FILES)
    await clickText('Assess')
    await settle()

    expect(text()).toMatch(new RegExp(`${SERVER_TOTAL} documents`))
    expect(barPct()).toBe(Math.round((SCORED / SERVER_TOTAL) * 100))
  })

  it('still shows a sane percentage when the server reports no total at all', async () => {
    // The invariant: with no run.files the component must fall back to what it does know rather
    // than dividing by zero or rendering NaN%. Passes before AND after.
    assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 4, worker_tier_alive: true })
    getScan.mockResolvedValue({ run: {}, files: [
      { file: 'a.docx', score: 90, status: 'done' },
      { file: 'b.docx', score: null, status: 'discovered' },
    ] })
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'running', phase: 'assessing' })

    await mount([{ file: 'a.docx', score: null, status: 'discovered' },
                 { file: 'b.docx', score: null, status: 'discovered' }])
    await clickText('Assess')
    await settle()

    const shown = barPct()
    expect(shown).not.toBeNull()
    expect(Number.isFinite(shown)).toBe(true)
    expect(shown).toBeGreaterThanOrEqual(0)
    expect(shown).toBeLessThanOrEqual(100)
  })
})

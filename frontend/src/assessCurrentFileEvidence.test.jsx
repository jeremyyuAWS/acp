/**
 * Assess must not name one document as the one being processed, because it cannot know that.
 *
 * The inference is stated in the code it comes from:
 *
 *     // The first file with no score yet is the one in flight.
 *     setCurrentFile(nameOf(fs.find((x) => x.score == null)))
 *
 * That is a guess dressed as a fact, and three things make it one:
 *
 *  * There is no per-file execution signal to read. `file_records` rows are INSERTed when a file
 *    FINISHES; a file that has not finished simply has no record, and `getScan` surfaces it from
 *    scan_inventory as 'discovered'. `score == null` therefore means "no result yet" — it does not
 *    mean "a worker has this open".
 *
 *  * Assessment is CONCURRENT. Production runs a 12-slot worker pool (readyz: `pool_size: 12`), so
 *    at any moment roughly twelve documents are in flight, not one. Picking the first of them and
 *    captioning it as the file being worked is arbitrary even when it happens to be true.
 *
 *  * The list order is the query's, not the worker's. `fs.find` returns whatever sorts first among
 *    the unfinished, which need not be the oldest, the newest, or the one anybody is holding.
 *
 * The PRD names this directly — "avoid claiming a specific file is processing without execution
 * evidence", and for parallel work "show multiple active folders rather than inventing one serial
 * current folder".
 *
 * The filename is still worth showing: it tells a user where a long run has got to, which is why
 * it was added. What changes is the CLAIM. It is labelled as the first document still awaiting a
 * result — which is exactly what `score == null` supports — instead of being presented bare
 * inside a "running" card, where it reads as "this is what we are working on now".
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

const MIDRUN = {
  run: { files: 4 },
  files: [
    { file: 'alpha.docx', score: 90, status: 'done' },
    { file: 'beta.docx', score: null, status: 'discovered' },
    { file: 'gamma.docx', score: null, status: 'discovered' },
    { file: 'delta.docx', score: null, status: 'discovered' },
  ],
}
const PROP_FILES = [
  { file: 'alpha.docx', score: null, status: 'discovered' },
  { file: 'beta.docx', score: null, status: 'discovered' },
]

beforeEach(() => {
  resetJobsFeed()
  assessScan.mockReset(); getScan.mockReset(); getQueueJob.mockReset()
  errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  try { sessionStorage.clear() } catch { /* ignore */ }
})
afterEach(() => { errSpy.mockRestore(); unmountAll(); resetJobsFeed() })

async function midRun() {
  assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 4, worker_tier_alive: true })
  getScan.mockResolvedValue(MIDRUN)
  getQueueJob.mockResolvedValue({ id: 'j1', status: 'running', phase: 'assessing' })
  await mount(PROP_FILES)
  await clickText('Assess')
  await settle()
}

describe('naming a document mid-run', () => {
  it('labels it as awaiting a result, not as the file being processed', async () => {
    await midRun()
    const el = container.querySelector('.assessfile')
    expect(el).not.toBeNull()
    // Assert on the LABEL, not on the whole node: an earlier draft of this test matched
    // /awaiting/i against textContent and passed on unmodified code, because the FIXTURE
    // FILENAME contained the word. A check that cannot fail is not a check.
    const label = el.querySelector('.assessfilelabel')
    expect(label, 'expected an explicit label for what the named file is').not.toBeNull()
    expect(label.textContent).toMatch(/awaiting/i)
  })

  it('still shows which document it is — the information is not removed', async () => {
    await midRun()
    expect(container.querySelector('.assessfile').textContent).toContain('beta.docx')
  })

  it('does not describe it with in-flight language', async () => {
    await midRun()
    const el = container.querySelector('.assessfile')
    // "Opening & assessing N of M" is the run-level caption and stays; what must not appear is a
    // per-FILE claim that this document specifically is open right now.
    const perFile = el.querySelector('.assessfname')?.parentElement?.textContent || ''
    expect(perFile).not.toMatch(/\bnow (?:opening|assessing|processing)\b/i)
    expect(perFile).not.toMatch(/\bcurrently\b/i)
  })

  it('names nothing once every document has a result', async () => {
    // The invariant: with no unfinished file there is nothing to name, before OR after.
    assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 4, worker_tier_alive: true })
    getScan.mockResolvedValue({
      run: { files: 2, assessed_at: new Date().toISOString() },
      files: [{ file: 'a.docx', score: 90, status: 'done' },
              { file: 'b.docx', score: 80, status: 'done' }],
    })
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'done' })
    await mount([{ file: 'a.docx', score: null, status: 'discovered' }])
    await clickText('Assess')
    await settle()

    const el = container.querySelector('.assessfile')
    if (el) expect(el.textContent).not.toMatch(/awaiting/i)
  })
})

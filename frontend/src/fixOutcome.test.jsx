/**
 * R8 · If a fix fails.
 *
 * The whole point of this component is a distinction, so the tests are built around it: a run that
 * FAILED, a run that REFUSED, and a document nothing was ATTEMPTED on must come out as three
 * different states from three different persisted rows — plus the two the record also supports and
 * which a four-state design would quietly fold in (a scan that never read the file, and a fix that
 * was written and did not clear).
 *
 * Two claims about the shipped backend are pinned here rather than trusted:
 *   · a failed Drive mirror is NOT a failed fix (ADR 0010 — Blob is the must-succeed write), and
 *   · nothing renders before both feeds answer, because an empty failure list asserts that
 *     everything worked.
 *
 * DOM-level, not browser-level: vite serves the SHARED checkout whatever worktree you are in
 * (CLAUDE.md), so a browser check would exercise code without this.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const getJobs = vi.fn()
const listScanDecisions = vi.fn()
const remediateScan = vi.fn(async () => ({ enqueued: 1 }))
const clearDeadJobs = vi.fn(async () => ({ purged: 0 }))
const rescoreFile = vi.fn(async () => ({ job_id: 'r1' }))

vi.mock('./api.js', () => ({
  getJobs: (...a) => getJobs(...a),
  listScanDecisions: (...a) => listScanDecisions(...a),
  remediateScan: (...a) => remediateScan(...a),
  clearDeadJobs: (...a) => clearDeadJobs(...a),
  rescoreFile: (...a) => rescoreFile(...a),
}))

const { outcomeFor, outcomeSummary, autoLaneSize, OUTCOMES } = await import('./fixOutcome.js')
const FixOutcomes = (await import('./FixOutcomes.jsx')).default
const { CAPABILITY_FALLBACK } = await import('./capability.js')

afterEach(unmountAll)
beforeEach(() => {
  getJobs.mockReset(); listScanDecisions.mockReset(); remediateScan.mockClear()
  getJobs.mockResolvedValue({ jobs: [] })
  listScanDecisions.mockResolvedValue([])
  remediateScan.mockResolvedValue({ enqueued: 1 })
})

const dec = (action, file, detail = '', ts = '2026-08-20T10:00:00Z') =>
  ({ id: action + file, ts, actor: 'system', action, scan_id: 's1', file, rule_id: null, detail })
const remJob = (file, over = {}) =>
  ({ id: 'j-' + file, type: 'remediate_file', scan_id: 's1', payload: JSON.stringify({ file }),
     status: 'done', attempts: 1, max_attempts: 5, ...over })

const flush = async () => { await act(async () => { await Promise.resolve(); await Promise.resolve() }) }
async function mount(props) {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(FixOutcomes, props)) })
  await flush()
  return container
}
const btn = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent))

// ── the distinction this component exists for ───────────────────────────────
describe('failed, refused and never-attempted are three different states', () => {
  const jobs = [remJob('broke.docx', { status: 'dead', attempts: 5, last_error: 'Drive token expired' })]
  const decisions = [dec('remediate.deferred', 'plain.pptx', '.pptx: no deterministic fixes applied')]
  const ctx = { scanId: 's1', decisions, jobs }

  it('a dead remediation job is `failed`, with the job’s own error as the reason', () => {
    const r = outcomeFor('broke.docx', ctx)
    expect(r.outcome).toBe('failed')
    expect(r.reason).toBe('Drive token expired')
    expect(r.reasonSource).toBe('job')
    expect(r.retryable).toBe(true)
    expect(r.job.kind).toBe('dead')
  })

  it('a run that declined is `refused`, and is NOT retryable', () => {
    const r = outcomeFor('plain.pptx', ctx)
    expect(r.outcome).toBe('refused')
    expect(r.retryable).toBe(false)
    expect(r.detail).toMatch(/no deterministic fixes applied/)
    expect(r.reason).toMatch(/nothing in it was in the automatic lane/i)
  })

  it('a document with no job and no decision row is `not_attempted`, not failed', () => {
    const r = outcomeFor('untouched.xlsx', ctx)
    expect(r.outcome).toBe('not_attempted')
    expect(r.reason).toBe('')
    expect(r.retryable).toBe(false)
  })

  it('the three never collapse into each other', () => {
    const s = outcomeSummary(['broke.docx', 'plain.pptx', 'untouched.xlsx'], ctx)
    expect(s.failed.map((r) => r.file)).toEqual(['broke.docx'])
    expect(s.refused.map((r) => r.file)).toEqual(['plain.pptx'])
    expect(s.not_attempted.map((r) => r.file)).toEqual(['untouched.xlsx'])
  })
})

// ── the two states a three-state design would fold in ───────────────────────
describe('the record supports two further states, and they are kept apart', () => {
  it('a scan that never read the file is `unreadable`, not a remediation failure', () => {
    const r = outcomeFor('gone.pdf', { scanId: 's1', jobs: [],
      decisions: [dec('scan.file_error', 'gone.pdf', 'HttpError 404: File not found')] })
    expect(r.outcome).toBe('unreadable')
    expect(r.reason).toMatch(/HttpError 404/)
    expect(r.retryable).toBe(false)
  })

  it('a fix that was written and did not clear is `unverified`, and outranks `applied`', () => {
    // handlers.py logs BOTH in one run when it credits some criteria and keeps others.
    const r = outcomeFor('half.docx', { scanId: 's1', jobs: [],
      decisions: [
        dec('remediate.applied', 'half.docx', 'set document title', '2026-08-20T10:00:02Z'),
        dec('remediate.unverified', 'half.docx',
            '2 verified cleared; 1 reported-fixed but still failing on re-scan (kept for review): 3.1.1',
            '2026-08-20T10:00:01Z'),
      ] })
    expect(r.outcome).toBe('unverified')
    expect(r.reason).toMatch(/still failing on re-scan/)
    // the applied row is not lost — both remarks survive as notes
    expect(r.notes.map((n) => n.action).sort()).toEqual(['remediate.applied', 'remediate.unverified'])
  })

  it('a queued job is reported as in flight, not as an outcome', () => {
    const r = outcomeFor('pending.docx', { scanId: 's1', decisions: [],
      jobs: [remJob('pending.docx', { status: 'queued', attempts: 0 })] })
    expect(r.outcome).toBe('not_attempted')
    expect(r.job.kind).toBe('in_flight')
    expect(r.reason).toMatch(/in the queue and has not finished/)
  })
})

// ── ADR 0010 ────────────────────────────────────────────────────────────────
describe('a failed Drive mirror is not a failed fix (ADR 0010)', () => {
  const decisions = [
    dec('remediate.applied', 'ok.docx', 'set document title', '2026-08-20T10:00:02Z'),
    dec('remediate.drive_mirror_failed', 'ok.docx', 'HttpError 403: insufficient permissions',
        '2026-08-20T10:00:01Z'),
  ]
  it('the outcome stays `applied` and the mirror failure is an annotation', () => {
    const r = outcomeFor('ok.docx', { scanId: 's1', decisions, jobs: [] })
    expect(r.outcome).toBe('applied')
    expect(r.mirrorFailed).toBe(true)
    expect(r.mirrorDetail).toMatch(/403/)
  })
})

// ── scoping and loading ─────────────────────────────────────────────────────
describe('scoping and absence', () => {
  it('another scan’s dead remediation job is not this scan’s failure', () => {
    const jobs = [remJob('x.docx', { scan_id: 'OTHER', status: 'dead', attempts: 5, last_error: 'boom' })]
    expect(outcomeFor('x.docx', { scanId: 's1', decisions: [], jobs }).outcome).toBe('not_attempted')
    expect(outcomeFor('x.docx', { scanId: 'OTHER', decisions: [], jobs }).outcome).toBe('failed')
  })

  it('an unloaded feed yields null, never `not_attempted`', () => {
    expect(outcomeFor('x.docx', { scanId: 's1', decisions: null, jobs: null, loaded: false })).toBe(null)
    expect(outcomeSummary(['x.docx'], { scanId: 's1', loaded: false })).toBe(null)
  })

  it('OUTCOMES orders the states worst-first', () => {
    expect(OUTCOMES[0]).toBe('failed')
    expect(OUTCOMES[OUTCOMES.length - 1]).toBe('not_attempted')
  })
})

// ── the automatic lane, derived not asserted ────────────────────────────────
describe('autoLaneSize explains a refusal from the capability table', () => {
  const cap = CAPABILITY_FALLBACK
  it('counts only the deterministic lane, per format', () => {
    const f = { file: 'a.docx', type: 'docx',
                issues: [{ wcag: 'SC_1_3_1' }, { wcag: 'SC_1_1_1' }, { wcag: 'SC_2_1_2' }] }
    expect(autoLaneSize(f, cap)).toBe(1)          // 1.3.1 auto; 1.1.1 assisted; 2.1.2 human
    expect(autoLaneSize({ ...f, type: 'html' }, cap)).toBe(1)   // html 1.1.1 is human, 1.3.1 auto
  })
  it('returns null rather than 0 when it has not been given what it needs', () => {
    expect(autoLaneSize(null, cap)).toBe(null)
    expect(autoLaneSize({ file: 'a.docx', type: 'docx' }, cap)).toBe(null)
    expect(autoLaneSize({ file: 'a.docx', type: 'docx', issues: [] }, null)).toBe(null)
  })
})

// ── rendering ───────────────────────────────────────────────────────────────
describe('FixOutcomes rendering', () => {
  it('renders nothing before either feed has answered', async () => {
    let resolve
    listScanDecisions.mockReturnValue(new Promise((r) => { resolve = r }))
    const c = await mount({ scanId: 's1', files: ['a.docx'] })
    expect(c.textContent).toBe('')
    await act(async () => { resolve([]) })
  })

  it('names each state on its own row and does not label a refusal a failure', async () => {
    getJobs.mockResolvedValue({ jobs: [
      remJob('broke.docx', { status: 'dead', attempts: 5, last_error: 'PdfReadError: corrupt' }),
    ] })
    listScanDecisions.mockResolvedValue([
      dec('remediate.deferred', 'plain.pptx', '.pptx: no deterministic fixes applied'),
    ])
    const c = await mount({ scanId: 's1', files: ['broke.docx', 'plain.pptx', 'untouched.xlsx'],
                            show: ['failed', 'refused', 'not_attempted'] })
    const rows = [...c.querySelectorAll('.fixoutcome-row')]
    expect(rows.map((r) => r.getAttribute('data-outcome')))
      .toEqual(['failed', 'refused', 'not_attempted'])
    const state = (o) => c.querySelector(`.fixoutcome-row[data-outcome="${o}"] .fixoutcome-state`).textContent
    expect(state('failed')).toMatch(/The fix failed/)
    expect(state('refused')).toMatch(/Not attempted by design/)
    expect(state('not_attempted')).toMatch(/No record of an attempt/)
    // the raw error is shown verbatim, not paraphrased
    expect(c.textContent).toMatch(/PdfReadError: corrupt/)
  })

  it('offers a retry only on the terminal failure, and it re-runs the originating action', async () => {
    getJobs.mockResolvedValue({ jobs: [
      remJob('broke.docx', { status: 'dead', attempts: 5, last_error: 'timeout' }),
    ] })
    listScanDecisions.mockResolvedValue([
      dec('remediate.deferred', 'plain.pptx', '.pptx: no deterministic fixes applied'),
    ])
    const c = await mount({ scanId: 's1', files: ['broke.docx', 'plain.pptx'] })
    expect(c.querySelectorAll('button').length).toBe(1)   // exactly one retry, on the dead job
    await act(async () => { btn(c, /Retry this document/).click() })
    await flush()
    expect(remediateScan).toHaveBeenCalledWith('s1', ['broke.docx'])
    expect(c.textContent).toMatch(/re-queued/i)
  })

  it('a job still being retried is shown, and offers no retry button', async () => {
    getJobs.mockResolvedValue({ jobs: [
      remJob('slow.docx', { status: 'running', attempts: 2, last_error: 'connection reset' }),
    ] })
    const c = await mount({ scanId: 's1', files: ['slow.docx'] })
    expect(c.querySelector('.fixoutcome-row[data-outcome="failed"]')).toBeTruthy()
    expect(c.textContent).toMatch(/retrying · 2\/5 attempts/)
    expect(btn(c, /Retry this document/)).toBeUndefined()
  })

  it('says when no reason was recorded, rather than supplying one', async () => {
    listScanDecisions.mockResolvedValue([dec('remediate.skipped', 'shadow.docx', '')])
    const c = await mount({ scanId: 's1', files: ['shadow.docx'] })
    expect(c.querySelector('.fixoutcome-row[data-outcome="refused"] .fixoutcome-reason').textContent)
      .toMatch(/ACP’s own remediated output/)
    // the DETAIL was empty and nothing was invented in its place
    expect(c.textContent).not.toMatch(/unreadable/i)
  })

  /**
   * The banned-vocabulary assertion is scoped to the row's own state line, NOT to the section. The
   * explanatory copy above the rows exists precisely to name all four situations, so a page-wide
   * regex for "failed" matches the sentence that explains that a refusal is not a failure.
   */
  it('a refused row’s state line never uses failure vocabulary', async () => {
    listScanDecisions.mockResolvedValue([
      dec('remediate.out_of_scope', 'scoped.docx', '1.4.3 is outside the operator scope — 2 proposal(s) not enqueued'),
    ])
    const c = await mount({ scanId: 's1', files: ['scoped.docx'] })
    const line = c.querySelector('.fixoutcome-row[data-outcome="refused"] .fixoutcome-state').textContent
    expect(line).not.toMatch(/fail|error|broke/i)
    // and the section as a whole DOES discuss failure, which is why the assertion above is scoped
    expect(c.textContent).toMatch(/failed/i)
  })

  it('a mirror failure over a successful fix reads as a missing copy, not a failed fix', async () => {
    listScanDecisions.mockResolvedValue([
      dec('remediate.applied', 'ok.docx', 'set document title', '2026-08-20T10:00:02Z'),
      dec('remediate.drive_mirror_failed', 'ok.docx', 'HttpError 403', '2026-08-20T10:00:01Z'),
    ])
    const c = await mount({ scanId: 's1', files: ['ok.docx'], show: ['applied'] })
    const row = c.querySelector('.fixoutcome-row[data-outcome="applied"]')
    expect(row.querySelector('.fixoutcome-state').textContent).toMatch(/Fixed/)
    expect(row.querySelector('.fixoutcome-mirror').textContent).toMatch(/only the drive mirror is missing/)
  })

  it('says the automatic lane was empty only when it was told the findings', async () => {
    listScanDecisions.mockResolvedValue([
      dec('remediate.deferred', 'manual.docx', '.docx: no deterministic fixes applied'),
    ])
    const withFindings = await mount({
      scanId: 's1', cap: CAPABILITY_FALLBACK,
      files: [{ file: 'manual.docx', type: 'docx', issues: [{ wcag: 'SC_1_1_1' }] }],  // assisted only
    })
    expect(withFindings.querySelector('.fixoutcome-autolane')).toBeTruthy()

    const withoutFindings = await mount({ scanId: 's1', files: ['manual.docx'] })
    expect(withoutFindings.querySelector('.fixoutcome-autolane')).toBeNull()
  })
})

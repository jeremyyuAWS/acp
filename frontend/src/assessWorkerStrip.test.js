/**
 * The worker status strip reports counts that are actually measured.
 *
 * #664 replaced the ambiguous "12 active · 0 waiting" broker internals with user-facing counts,
 * and introduced one that could never appear: "assigned next", computed as
 * `inFlight - workersBusy`. The backend sets `workers.busy = in_flight` by construction
 * (api/live_queue.py compose), so that subtraction is always exactly 0 — the category was dead
 * markup in a strip whose only job is to say where the work is.
 *
 * The distinction it reached for (claimed-by-a-worker vs actively-being-assessed) is real, but
 * nothing scan-scoped reports it: `workerSnap.running` is the jobs table SYSTEM-WIDE, across every
 * scan and user, so subtracting a per-scan number from it yields a figure belonging to neither.
 * tests/test_live_queue.py pins the backend half of this.
 *
 * COMMENTS ARE STRIPPED BEFORE ASSERTING. The source carries an explanation of why the category is
 * gone, and that explanation necessarily names it — a whole-file regex would match the comment and
 * pass (or fail) for the wrong reason. CLAUDE.md records this exact trap biting twice; the fix is to
 * scope the assertion to the code making the claim, which here means the file minus its prose.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const raw = readFileSync(join(here, 'AssessRunner.jsx'), 'utf8')

/** The source with comments removed, so an assertion reads the code and not the explanation. */
const code = raw
  .replace(/\/\*[\s\S]*?\*\//g, ' ')      // /* … */ and JSX {/* … */} bodies
  .replace(/^\s*\/\/.*$/gm, ' ')          // whole-line //
  .replace(/([^:])\/\/.*$/gm, '$1')       // trailing // (leaves https:// alone)

describe('the worker strip does not render a count it cannot measure', () => {
  it('the comment-stripping helper actually works', () => {
    // Guard the guard: if this regex ever stops removing comments, every assertion below starts
    // reading prose and silently proves nothing.
    expect(raw).toMatch(/NO "assigned next" COUNT/)      // the explanation is present in the file
    expect(code).not.toMatch(/NO "assigned next" COUNT/) // …and absent from the stripped code
  })

  it('no "assigned next" label survives in the rendered markup', () => {
    expect(code).not.toMatch(/assigned next/i)
  })

  it('the always-zero subtraction is gone', () => {
    expect(code).not.toMatch(/inFlight\s*-\s*.*workersBusy/)
    expect(code).not.toMatch(/assignedCount/)
  })

  it('the two counts that ARE measured are still rendered', () => {
    // Deleting the dead category must not take the live ones with it.
    expect(code).toMatch(/processingCount\s*=\s*liveQueue \? liveQueue\.workersBusy : 0/)
    expect(code).toMatch(/\{processingCount > 0 &&/)
    expect(code).toMatch(/\{brokerQueued > 0 &&/)
    expect(code).toMatch(/completed/)
  })

  it('the queued fallback no longer subtracts the removed term', () => {
    // brokerQueued's no-liveQueue fallback used to subtract assignedCount, which was always 0 —
    // harmless arithmetic, but it kept a dead variable alive and reachable.
    expect(code).toMatch(/brokerQueued = liveQueue \? liveQueue\.queued : Math\.max\(0, assessN - progress - processingCount\)/)
  })
})

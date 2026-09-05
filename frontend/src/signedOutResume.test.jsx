import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// The wiring, at source level — the split this codebase already uses for these two components
// (see remediateProcessingStatusWiring.test.jsx's header: Remediate.jsx pulls in a dozen panels
// that would all need mocking to reach one effect). The DECISION is unit-tested on its own in
// resumeInFlight.test.js; what is asserted here is that each component actually asks the server,
// and only when it has no local state to prefer.
//
// WHY IT NEEDS A GUARD AT ALL. Sign out is a deliberate total wipe: App.jsx runs
// clearActivityStorage() over every `acp-` sessionStorage key, then sessionStorage.clear() and a
// hard reload — "no scan, decisions, assess phase, or files survive". The jobs do not stop; the
// queue is durable. So the card's only route back to a running batch is the server, and Discovery
// was the only lane that had one (GET /scans/active).

const here = dirname(fileURLToPath(import.meta.url))
const remediate = readFileSync(join(here, 'Remediate.jsx'), 'utf8')
const assess = readFileSync(join(here, 'AssessRunner.jsx'), 'utf8')

describe('the remediation card rejoins a batch the browser has forgotten', () => {
  it('asks the server when sessionStorage has no denominator', () => {
    expect(remediate).toMatch(/import \{ remediationResume \} from '\.\/resumeInFlight\.js'/)
    expect(remediate).toMatch(/if \(!saved\?\.total\) \{/)
    expect(remediate).toMatch(/getRemediationStatus\(runId\)\.then\(\(s\) => \{/)
    expect(remediate).toMatch(/const resume = remediationResume\(s\)/)
  })

  it('prefers local state, so the reconnect can never fight the existing resume', () => {
    // The saved-total branch still runs first and returns; the server call is the else.
    const savedFirst = remediate.indexOf('if (saved?.total) { setRemBusy(true)')
    const serverAfter = remediate.indexOf('if (!saved?.total) {')
    expect(savedFirst).toBeGreaterThan(-1)
    expect(serverAfter).toBeGreaterThan(savedFirst)
  })

  it('starts the same live updates a fresh run does, not a second mechanism', () => {
    expect(remediate).toMatch(/startLiveUpdates\(resume\.total\)/)
  })

  it('re-seeds the denominator so a later remount in this tab costs nothing', () => {
    expect(remediate).toMatch(/sessionStorage\.setItem\(REMKEY\(runId\), JSON\.stringify\(\{ total: resume\.total \}\)\)/)
  })

  it('cancels on unmount, and stays idle when there is nothing to rejoin', () => {
    expect(remediate).toMatch(/if \(cancelled\) return/)
    expect(remediate).toMatch(/return \(\) => \{ cancelled = true \}/)
    expect(remediate).toMatch(/if \(!resume\) return/)
    expect(remediate).toMatch(/\.catch\(\(\) => \{ \/\* no reconnect available/)
  })
})

describe('the assess screen rejoins a run the browser has forgotten', () => {
  it('asks /scans/{sid}/live when there is no saved pass', () => {
    expect(assess).toMatch(/import \{ assessResume \} from '\.\/resumeInFlight\.js'/)
    expect(assess).toMatch(/getScanLive\(runId\)\.then\(\(snap\) => \{/)
    expect(assess).toMatch(/const resume = assessResume\(snap\)/)
  })

  it('only when idle, and only once per run id', () => {
    // The effect re-runs as `docs` fills in; a reconnect is a decision about the run, not about
    // how many documents have arrived, so a second attempt would double-start the poll.
    expect(assess).toMatch(/if \(!runId \|\| phase !== 'idle' \|\| serverResumeRef\.current === runId\) return undefined/)
    expect(assess).toMatch(/serverResumeRef\.current = runId/)
  })

  it('rejoins through the deferred poll the running screen already uses', () => {
    expect(assess).toMatch(/pollDeferred\(startedAt, null\)/)
    expect(assess).toMatch(/save\(\{ phase: 'running', deferred: true, startedAt, level \}\)/)
  })

  it('leaves the saved-pass resume ahead of it, and returns from that branch', () => {
    const savedBranch = assess.indexOf("if (saved?.phase === 'running')")
    const serverBranch = assess.indexOf('const resume = assessResume(snap)')
    expect(savedBranch).toBeGreaterThan(-1)
    expect(serverBranch).toBeGreaterThan(savedBranch)
    expect(assess).toMatch(/if \(saved\.deferred\) \{ pollDeferred\(saved\.startedAt \|\| Date\.now\(\), saved\.jobId\); return undefined \}/)
  })
})

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Proves Remediate.jsx actually wires the queue-pickup estimate into ProcessingStatusPanel —
// deriveRemediateProcessingState is covered on its own (remediateProcessingState.test.js).
// SOURCE-level, not DOM: Remediate.jsx has no existing DOM-mount test harness (it pulls in
// RemediationInbox, ReviewDrawer, and a dozen other panels that would all need mocking just to
// reach this one poll) — matching the SOURCE/DOM/unit split this codebase already uses for the
// same tradeoff elsewhere (see discoverProcessingStatusWiring.test.jsx's own header comment, and
// remediateWiring.test.jsx's own source-level composition check for the sibling precedent within
// this exact file).

const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'Remediate.jsx'), 'utf8')

describe('the queue-estimate poll is wired into Remediate', () => {
  it('polls getQueueEstimate(runId, "remediate") only while enqueued and nothing has completed yet', () => {
    expect(src).toMatch(/getQueueEstimate\(runId, 'remediate'\)/)
    expect(src).toMatch(/const waiting = remBusy && \(!remProg \|\| remProg\.done === 0\)/)
    expect(src).toMatch(/if \(!waiting \|\| !runId\) return undefined/)
  })

  it('stops polling once remProg.done advances — the effect deps include it', () => {
    expect(src).toMatch(/\}, \[remBusy, remProg\?\.done, runId\]\)/)
  })

  it('mounts ProcessingStatusPanel fed from deriveRemediateProcessingState with the live signals', () => {
    expect(src).toMatch(
      /<ProcessingStatusPanel derived=\{deriveRemediateProcessingState\(\{ remBusy, remProg, pickupEstimate, updateMode: remUpdates \}\)\} \/>/)
  })

  it('prefers the authenticated remediation SSE stream and retains polling as fallback', () => {
    // THE GUARANTEE IS UNCHANGED; ITS OWNER MOVED. Remediate no longer opens the stream —
    // `useRemediationRun` does, at App level, because this component is unmounted on every tab
    // change and a connection that dies with it cannot keep a run watched, cannot keep ADR 0051's
    // resume cursor across tabs, and cannot let the persistent card say "Live" honestly.
    //
    // So this asserts the same two properties at their new address: exactly one opener, and
    // polling still covering the disconnected case.
    const hook = readFileSync(join(here, 'useRemediationRun.js'), 'utf8')
    expect(hook).toMatch(/openRemediationStream\(runId/)
    expect(hook).toMatch(/onError:/)
    expect(hook).toMatch(/startPoll\(\)/)
    // Remediate consumes the frames rather than owning the socket. A second opener here would
    // put two streams on one run, which is what moving ownership was for.
    expect(src).not.toMatch(/openRemediationStream\(/)
    // ...and it still polls the LEGACY status shape while disconnected, because the hook's own
    // fallback fetches the reconciled snapshot, not the shape the progress bar reads.
    expect(src).toMatch(/startPoll\(watchTotalRef\.current\)/)
  })

  it('puts the SSE-fed remediation progress card in the main workflow', () => {
    expect(src).toMatch(/import RemediationRunProgress from '\.\/RemediationRunProgress\.jsx'/)
    // The card remains mounted for its final completed snapshot after remBusy turns false.
    expect(src).toMatch(/remProg && \([\s\S]*?<RemediationRunProgress progress=\{remProg\} updateMode=\{remUpdates\}/)
  })
})

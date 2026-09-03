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
    expect(src).toMatch(/openRemediationStream\(runId/)
    expect(src).toMatch(/onError: \(\) => \{ streamRef\.current = null; startPoll\(total\) \}/)
  })

  it('puts the SSE-fed remediation progress card in the main workflow', () => {
    expect(src).toMatch(/import RemediationRunProgress from '\.\/RemediationRunProgress\.jsx'/)
    // The card remains mounted for its final completed snapshot after remBusy turns false.
    expect(src).toMatch(/remProg && \([\s\S]*?<RemediationRunProgress progress=\{remProg\} updateMode=\{remUpdates\}/)
  })
})

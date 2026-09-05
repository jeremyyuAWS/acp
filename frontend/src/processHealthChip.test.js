/**
 * processHealthChip.test.js
 *
 * Source-level tests confirming that the process-health chip is present in
 * App.jsx and that all three severity states (worker error, unreadable files,
 * healthy) are covered.
 *
 * These tests operate on the raw JSX source text rather than a rendered DOM
 * so they are immune to the import complexity of App.jsx's many dependencies
 * and still give a clear, fast signal when the chip is accidentally removed
 * or its logic is changed.
 */

import fs from 'fs'
import path from 'path'
import { describe, it, expect } from 'vitest'

const SRC = fs.readFileSync(
  path.resolve(import.meta.dirname, 'App.jsx'),
  'utf8'
)

describe('process-health chip', () => {
  it('is gated on run?.completed_at so it never shows during an in-flight scan', () => {
    expect(SRC).toContain('run?.completed_at')
  })

  it('derives unreadable count from allFiles with status === error', () => {
    // Derived once, above the header, because the chip and the context bar both read it — see
    // "never claims Verified while it is also reporting an exception".
    expect(SRC).toContain("allFiles.filter((f) => f.status === 'error').length")
  })

  it('detects the worker-error state via run?.status === failed', () => {
    // The chip must check the run status for the highest-severity state.
    expect(SRC).toContain("run?.status === 'failed'")
  })

  it('labels the worker-error state "Worker error"', () => {
    expect(SRC).toContain("'Worker error'")
  })

  it('labels the unreadable-files state with the dynamic count', () => {
    // The label is a template literal that interpolates the count.
    expect(SRC).toContain('`${unreadable} unreadable`')
  })

  // THE HEALTHY STATE MOVED; it was not deleted. The compact header reports exceptions in this
  // chip and reports health by the chip's ABSENCE, with "✓ Verified" in the context bar below
  // carrying the affirmative signal. These two tests follow it there rather than being dropped:
  // what the original guard protected — that all three states are covered and each is explained —
  // still has to hold, or a clean run becomes indistinguishable from a run that never reported.
  it('renders nothing at all when the run is healthy', () => {
    expect(SRC).toContain("if (!workerError && unreadable === 0) return null")
  })

  it('reports the healthy state affirmatively in the context bar', () => {
    expect(SRC).toContain('context-verified')
    expect(SRC).toContain('✓ Verified')
  })

  it('never claims Verified while it is also reporting an exception', () => {
    // The two ends of one ordering (worker error > unreadable > healthy). Gated only on
    // `status !== 'failed'`, the bar showed "✓ Verified" beside the amber "N unreadable" chip —
    // one saying files were skipped, the other that everything checked out.
    expect(SRC).toContain("{run?.completed_at && !workerError && unreadableFiles === 0 && (")
  })

  it('explains both exception states in a tooltip', () => {
    expect(SRC).toContain('Assessment stopped due to a processing failure')
    expect(SRC).toContain('could not be opened and were skipped')
  })

  it('renders the chip as a <span> with a title tooltip (no click handler required)', () => {
    // The chip uses `title={chipTip}` for the popover — native, accessible, zero JS.
    expect(SRC).toContain('title={chipTip}')
  })

  it('applies a pill shape (borderRadius 20) and a color-coded background', () => {
    expect(SRC).toContain('borderRadius: 20')
    expect(SRC).toContain('background: chipBg')
    expect(SRC).toContain('color: chipColor')
  })

  it('chip is inside the header actions', () => {
    // Confirm the chip sits within the header's action group — not in the nav or main content.
    // The container was `.userbox` until the compact header replaced it with `.header-actions`;
    // the assertion is about WHERE the chip lives, so it follows the container's new name rather
    // than failing over it. (indexOf returns -1 for a missing container, which would make the
    // ordering comparison below pass vacuously — hence the explicit presence check first.)
    const actionsStart = SRC.indexOf('<div className="header-actions">')
    expect(actionsStart).toBeGreaterThan(-1)
    const actionsEnd = SRC.indexOf('</div>', actionsStart)
    const chipGate = SRC.indexOf('run?.completed_at')
    expect(chipGate).toBeGreaterThan(actionsStart)
    expect(chipGate).toBeLessThan(actionsEnd + 2000) // allow for deeply nested markup
  })
})

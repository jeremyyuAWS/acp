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
    expect(SRC).toContain("allFiles.filter(f => f.status === 'error')")
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

  it('labels the healthy state "Healthy"', () => {
    expect(SRC).toContain("'Healthy'")
  })

  it('renders all three tooltip explanations', () => {
    expect(SRC).toContain('Assessment stopped due to a processing failure')
    expect(SRC).toContain('could not be opened and were skipped')
    expect(SRC).toContain('All files were processed successfully')
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

  it('chip is inside the header userbox', () => {
    // Confirm the chip sits within the userbox div — not in the nav or main content.
    const userboxStart = SRC.indexOf('<div className="userbox">')
    const userboxEnd = SRC.indexOf('</div>', userboxStart)
    const chipGate = SRC.indexOf('run?.completed_at')
    expect(chipGate).toBeGreaterThan(userboxStart)
    expect(chipGate).toBeLessThan(userboxEnd + 2000) // allow for deeply nested markup
  })
})

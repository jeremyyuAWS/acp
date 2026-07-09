import { describe, it, expect } from 'vitest'
import { DISCOVER_LINES, ASSESS_LINES, discoverLine, assessLine } from './phaseNarration.js'

// A step's progress line may describe only the work that step performs. These run while the
// user watches a spinner and can't verify anything, so cross-step vocabulary is a lie with
// no cost to tell. Encode the rule; don't rely on remembering it.

const WCAG_CRITERION = /\b\d\.\d\.\d+\b/            // "1.1.1", "1.4.11"
const CONFORMANCE = /conformance|WCAG|AA\b|scoring against|score/i
const REMEDIATION = /remediat|fixing|auto-fix|applying|repair/i
const DISCOVERY = /download|parsing|extracting|crawl|listing|metadata/i
// Work the Assess step does not do — it re-opens no document.
const PARSING = /opening|unpack|tag tree|DOM|axe-core|transcrib|whisper|OOXML/i

describe('Discover narration', () => {
  it('never claims assessment — no WCAG criteria, no conformance scoring', () => {
    for (const line of DISCOVER_LINES) {
      expect(line, line).not.toMatch(WCAG_CRITERION)
      expect(line.replace(/for the Assess step/i, ''), line).not.toMatch(CONFORMANCE)
    }
  })

  it('never claims remediation — the scan fixes nothing', () => {
    for (const line of DISCOVER_LINES) expect(line, line).not.toMatch(REMEDIATION)
  })

  it('drops the PII line when deep scan is off, so it never claims work not running', () => {
    const off = Array.from({ length: 40 }, (_, i) => discoverLine(i * 5, false))
    expect(off.some((l) => /PII/.test(l))).toBe(false)
    expect(discoverLine(15, true) !== undefined).toBe(true)
    const on = Array.from({ length: 40 }, (_, i) => discoverLine(i * 5, true))
    expect(on.some((l) => /PII/.test(l))).toBe(true)
  })
})

describe('Assess narration', () => {
  it('never claims remediation — assessing decides nothing about fixes', () => {
    for (const line of ASSESS_LINES) expect(line, line).not.toMatch(REMEDIATION)
  })

  it('never claims discovery — the files were fetched and parsed by the scan', () => {
    for (const line of ASSESS_LINES) expect(line, line).not.toMatch(DISCOVERY)
  })

  it('never claims to open, parse, or transcribe a document', () => {
    // Assess is a client-side rollup over findings the scan already produced. It previously
    // said "Extracting PDF tag tree…" and "Transcribing with Whisper…" — Whisper is never
    // called anywhere in this step.
    for (const line of ASSESS_LINES) expect(line, line).not.toMatch(PARSING)
  })

  it('cycles through every line rather than stranding one unreachable', () => {
    // The old code indexed a 3-element array with `idx % 2`, so the third line never showed.
    const seen = new Set(Array.from({ length: 12 }, (_, i) => assessLine(i)))
    expect(seen.size).toBe(ASSESS_LINES.length)
  })
})

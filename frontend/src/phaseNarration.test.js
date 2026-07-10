import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { SCAN_PHASE_LINES, ASSESS_LINES, scanPhaseLine, assessLine } from './phaseNarration.js'

const here = dirname(fileURLToPath(import.meta.url))
const code = (f) => readFileSync(join(here, f), 'utf8')
  .split('\n').filter((l) => !l.trim().startsWith('//') && !l.trim().startsWith('*')).join('\n')

// A step's progress line may describe only the work that step performs, AND the line shown must
// be the line for the work happening right now. The old Discover narration was picked by a timer
// (`lines[Math.floor(elapsed / 5) % n]`), so it cycled through five plausible sentences
// regardless of the phase — the screen said "Downloading and parsing each document…" while the
// backend was scoring. Encode both rules; don't rely on remembering them.

const WCAG_CRITERION = /\b\d\.\d\.\d+\b/            // "1.1.1", "1.4.11"
const CONFORMANCE_LEVEL = /conformance|WCAG|\bAA\b|\bA\b conformant/   // the Assess step's job
const REMEDIATION = /remediat|fixing|auto-fix|applying|repair/i
const DISCOVERY = /download|parsing|extracting|crawl|listing|metadata/i
const PARSING = /opening|unpack|tag tree|DOM|axe-core|transcrib|whisper|OOXML/i

const SCAN_LINES = Object.values(SCAN_PHASE_LINES)

describe('the scan narration says what the scanner is doing, right now', () => {
  it('every phase the scanner emits has a line', () => {
    // api/scanner.py's progress() callback emits exactly these.
    for (const p of ['queued', 'connecting', 'discovering', 'reading', 'analysing', 'scoring', 'done']) {
      expect(scanPhaseLine(p), p).toBeTruthy()
    }
  })

  it('an unknown phase narrates nothing rather than guessing', () => {
    expect(scanPhaseLine('teleporting')).toBeNull()
    expect(scanPhaseLine(undefined)).toBeNull()
    expect(scanPhaseLine(null)).toBeNull()
  })

  it('never derives the line from elapsed time', () => {
    // The defect: identical inputs, different sentence, purely because seconds passed.
    const src = code('phaseNarration.js')
    expect(src).not.toMatch(/elapsed/)
    expect(src).not.toMatch(/Math\.floor\([^)]*\/\s*5\s*\)/)
    // And the function takes no time argument at all.
    expect(scanPhaseLine.length).toBeLessThanOrEqual(2)
  })

  it('the same phase always narrates the same thing', () => {
    for (const p of Object.keys(SCAN_PHASE_LINES)) {
      expect(scanPhaseLine(p)).toBe(scanPhaseLine(p))
    }
  })
})

describe('scan narration claims only the scan\'s work', () => {
  it('names no WCAG criterion — the scan finds issues, it does not rule on criteria', () => {
    for (const line of SCAN_LINES) expect(line, line).not.toMatch(WCAG_CRITERION)
  })

  it('claims no conformance level — that decision belongs to Assess', () => {
    // The scan DOES score (Rubric.assess -> 100 - penalties). It does not decide AA conformance.
    for (const line of SCAN_LINES) expect(line, line).not.toMatch(CONFORMANCE_LEVEL)
  })

  it('is allowed to say it scores, because it does', () => {
    // The previous contract forbade the word outright, encoding a belief the code contradicts.
    expect(SCAN_PHASE_LINES.scoring).toMatch(/scoring/i)
  })

  it('never claims remediation — the scan fixes nothing', () => {
    for (const line of SCAN_LINES) expect(line, line).not.toMatch(REMEDIATION)
  })

  it('names the PII deep scan only in the phase that runs it, and only when it is on', () => {
    expect(scanPhaseLine('analysing', { deepScan: true })).toMatch(/PII/)
    expect(scanPhaseLine('analysing', { deepScan: false })).not.toMatch(/PII/)
    for (const p of ['queued', 'connecting', 'discovering', 'reading', 'scoring', 'done']) {
      expect(scanPhaseLine(p, { deepScan: true }), p).not.toMatch(/PII/)
    }
  })
})

describe('App.jsx renders the phase, not a stopwatch', () => {
  const app = code('App.jsx')

  it('passes progress.phase into the narration everywhere', () => {
    expect(app).not.toMatch(/discoverLine/)
    const calls = app.match(/scanPhaseLine\([^)]*\)/g) || []
    expect(calls.length).toBeGreaterThanOrEqual(3)   // top bar + Discover + Monitor
    for (const c of calls) expect(c, c).toMatch(/progress\.phase/)
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
    for (const line of ASSESS_LINES) expect(line, line).not.toMatch(PARSING)
  })

  it('cycles through every line rather than stranding one unreachable', () => {
    const seen = new Set(Array.from({ length: 12 }, (_, i) => assessLine(i)))
    expect(seen.size).toBe(ASSESS_LINES.length)
  })
})

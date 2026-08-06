import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  SCAN_PHASE_LINES, ASSESS_LINES, PHASE_STEP, NARRATION_STEPS, scanPhaseLine, assessLine,
} from './phaseNarration.js'

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

// The phases api/scanner.py's progress() callback actually emits. One list, used by every test
// below, so a phase added to the scanner has exactly one place to be registered here.
const EMITTED = ['queued', 'connecting', 'discovering', 'reading', 'analysing', 'scoring', 'done']

// The vocabulary that describes HOW the conformance analysis works. True of the job, and the
// specific thing a step that isn't doing that work may not say. This is the defect: Discover
// rendered `analysing`'s line, "Extracting text, images and document structure…", under a tab
// subtitled "inventory · classify".
const EXTRACTION = /extract|text, images|document structure|analys(e|ing) (each )?document/i

describe('the scan narration says what the scanner is doing, right now', () => {
  it('every phase the scanner emits has a line', () => {
    for (const p of EMITTED) expect(scanPhaseLine(p), p).toBeTruthy()
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

// A line can be true about the JOB and still wrong about the STEP it is rendered under. The
// scan panel sits above <main>, so it appears inside whichever step is open — and `analysing`'s
// line described the conformance analysis while the Discover tab said "inventory · classify".
// ADR 0020 draws the boundary: Discover answers "what is this?", Assess answers "what's wrong
// with it?". PHASE_STEP records that assignment; these tests pin it so a phase added later
// cannot silently land on the wrong step.
describe('every phase is assigned to the step whose work it is', () => {
  it('every phase the scanner emits has an owner', () => {
    for (const p of EMITTED) expect(PHASE_STEP[p], p).toBeTruthy()
  })

  it('PHASE_STEP and SCAN_PHASE_LINES describe the same set of phases', () => {
    // Drift either way is the bug: a phase with a line but no owner defaults to being narrated
    // everywhere, and a phase with an owner but no line narrates nothing at all.
    expect(Object.keys(PHASE_STEP).sort()).toEqual(Object.keys(SCAN_PHASE_LINES).sort())
    expect(Object.keys(PHASE_STEP).sort()).toEqual([...EMITTED].sort())
  })

  it('every owner is a real step, or the explicit "any"', () => {
    for (const [p, owner] of Object.entries(PHASE_STEP)) {
      expect(owner === 'any' || NARRATION_STEPS.has(owner), `${p} → ${owner}`).toBe(true)
    }
    expect([...NARRATION_STEPS].sort()).toEqual(['assess', 'discover'])
  })

  it('the conformance-evaluation phases belong to Assess, not Discover', () => {
    // `analysing` is _analyse_one (api/scanner.py): the .NET/PDF/HTML analysers, OCR
    // images-of-text, sensory + language text checks, contrast and headings. `scoring` is
    // Rubric.assess() — a score and per-criterion pass/fail. Both answer "what's wrong with
    // it?", which is Assess's question under ADR 0020 regardless of which job runs them.
    expect(PHASE_STEP.analysing).toBe('assess')
    expect(PHASE_STEP.scoring).toBe('assess')
  })

  it('listing the estate belongs to Discover', () => {
    expect(PHASE_STEP.discovering).toBe('discover')
  })
})

describe('a step narrates a phase it does not own by naming the step that does', () => {
  const crossStep = EMITTED.flatMap((p) => [...NARRATION_STEPS]
    .filter((s) => PHASE_STEP[p] !== 'any' && PHASE_STEP[p] !== s)
    .map((s) => [p, s]))

  it('there is at least one cross-step pair to check', () => {
    expect(crossStep.length).toBeGreaterThan(0)   // else the tests below assert nothing
  })

  it('never reuses the phase\'s own line on a step that is not doing that work', () => {
    for (const [p, s] of crossStep) {
      expect(scanPhaseLine(p, { step: s }), `${p} on ${s}`).not.toBe(SCAN_PHASE_LINES[p])
    }
  })

  it('Discover does not describe the extraction — that was the defect', () => {
    // The regression, stated exactly: this is the sentence that sat under "inventory · classify".
    expect(scanPhaseLine('analysing', { step: 'discover' })).not.toBe(SCAN_PHASE_LINES.analysing)
    for (const p of ['analysing', 'scoring']) {
      expect(scanPhaseLine(p, { step: 'discover' }), p).not.toMatch(EXTRACTION)
      expect(scanPhaseLine(p, { step: 'discover', deepScan: true }), p).not.toMatch(EXTRACTION)
    }
  })

  it('says plainly that the assessment is running, and where it lands', () => {
    // The alternative was silence. Rejected: `analysing` is the longest phase, and a blank line
    // under a live spinner is its own kind of dishonesty. So it must say something, and what it
    // says must point at the step that owns the work.
    for (const p of ['analysing', 'scoring']) {
      const line = scanPhaseLine(p, { step: 'discover' })
      expect(line, p).toBeTruthy()
      expect(line, p).toMatch(/\bAssess step\b/)
      expect(line, p).toMatch(/assessment/i)
    }
  })

  it('still names the PII deep scan on Discover — sensitive data is inventory, not conformance', () => {
    // ADR 0006 sensitive-data detection runs inside `analysing` and answers "what is this?",
    // so Discover may name it. It is the only part of that phase Discover is entitled to.
    expect(scanPhaseLine('analysing', { step: 'discover', deepScan: true })).toMatch(/PII/)
    expect(scanPhaseLine('analysing', { step: 'discover', deepScan: false })).not.toMatch(/PII/)
    for (const p of EMITTED.filter((x) => x !== 'analysing')) {
      expect(scanPhaseLine(p, { step: 'discover', deepScan: true }), p).not.toMatch(/PII/)
    }
  })

  it('a step that OWNS the phase narrates it verbatim, with no gratuitous divergence', () => {
    for (const p of EMITTED) {
      const owner = PHASE_STEP[p]
      const steps = owner === 'any' ? [...NARRATION_STEPS] : [owner]
      for (const s of steps) {
        expect(scanPhaseLine(p, { step: s }), `${p} on ${s}`).toBe(SCAN_PHASE_LINES[p])
      }
    }
    // Assess owns `analysing`, so on the Assess step the extraction line is correct AND
    // correctly placed — the words were never the defect.
    expect(scanPhaseLine('analysing', { step: 'assess' })).toBe(SCAN_PHASE_LINES.analysing)
  })

  it('no step is given, no step scoping — the job narrates itself', () => {
    // The panel also renders on non-step views (Overview, Integrations), which have no step
    // vocabulary to be scoped to. Those must keep the job's own line, not fall silent.
    for (const p of EMITTED) expect(scanPhaseLine(p, { step: null }), p).toBe(scanPhaseLine(p))
  })

  it('an unknown step narrates nothing rather than guessing', () => {
    expect(scanPhaseLine('analysing', { step: 'teleporting' })).toBeNull()
  })

  it('no phase leaves a step with a blank line under a live spinner', () => {
    // Scoping a phase to a step must never be a way to say nothing. Silence is reserved for an
    // unknown phase, where there is genuinely nothing to say; every phase the scanner emits is
    // work we can name, on every step. This is what forces a phase added later to be given its
    // cross-step wording rather than quietly blanking a screen.
    for (const p of EMITTED) {
      for (const s of NARRATION_STEPS) {
        expect(scanPhaseLine(p, { step: s }), `${p} on ${s}`).toBeTruthy()
        expect(scanPhaseLine(p, { step: s, deepScan: true }), `${p} on ${s} (deep)`).toBeTruthy()
      }
    }
  })

  it('obeys the same vocabulary rules as every other scan line', () => {
    // These lines are not in SCAN_PHASE_LINES, so the contracts above skip them. A cross-step
    // line is still a scan line and may not smuggle in the vocabulary they forbid.
    const lines = crossStep.flatMap(([p, s]) => [
      scanPhaseLine(p, { step: s }), scanPhaseLine(p, { step: s, deepScan: true }),
    ]).filter(Boolean)
    expect(lines.length).toBeGreaterThan(0)
    for (const line of lines) {
      expect(line, line).not.toMatch(WCAG_CRITERION)
      expect(line, line).not.toMatch(CONFORMANCE_LEVEL)
      expect(line, line).not.toMatch(REMEDIATION)
    }
  })
})

describe('App.jsx renders the phase, not a stopwatch', () => {
  const app = code('App.jsx')

  it('passes progress.phase into the narration everywhere', () => {
    expect(app).not.toMatch(/discoverLine/)
    const calls = app.match(/scanPhaseLine\([^)]*\)/g) || []
    // This used to assert >= 3 "top bar + Discover + Monitor". Only the top bar ever rendered a
    // line: App.jsx computed a `scanStatus` prop for Discover and Monitor and both components
    // dropped it on the floor — accepted in the parameter list, never referenced in the body. The
    // count was pinning dead code, which is why the assertion passed while the panel the customer
    // was actually reading went unscoped. The dead props are gone; assert what renders.
    expect(calls.length).toBeGreaterThanOrEqual(1)
    for (const c of calls) expect(c, c).toMatch(/progress\.phase/)
  })

  it('scopes the narration to the step the panel is rendered in', () => {
    // The panel sits above <main>, so it appears inside whichever step is open. Every call must
    // pass the step, and the step must be derived from NARRATION_STEPS rather than hard-coded —
    // a step added to PHASE_STEP should not need a second edit here to be honoured.
    const calls = app.match(/scanPhaseLine\([^)]*\)/g) || []
    for (const c of calls) expect(c, c).toMatch(/step:/)
    expect(app).toMatch(/NARRATION_STEPS\.has\(view\)/)
  })

  it('no longer hands a narration prop to a component that ignores it', () => {
    expect(app).not.toMatch(/scanStatus=/)
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

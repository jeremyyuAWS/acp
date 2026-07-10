// The one-line "still working" narration under each step's progress bar.
//
// Rule: a step narrates ONLY the work it actually performs, and only work it performs. These
// lines are the most-read text in the product — they run while the user stares at a spinner
// with nothing else to do — and a line that claims work the step isn't doing is a lie the user
// has no way to check.
//
// The Discover narration used to be picked by a TIMER: `lines[Math.floor(elapsed / 5) % n]`.
// It cycled through five plausible sentences every five seconds regardless of what the scan
// was doing, so the screen said "Downloading and parsing each document…" while the backend was
// scoring. Exactly the fabricated-progress pattern deleted from the remediate queue (REM_STEPS).
// The narration now derives from `progress.phase`, which the scanner really emits.
//
// What the scan actually does, in order (api/scanner.py):
//   queued/connecting/discovering → list the estate
//   reading                       → download each document
//   analysing                     → engines extract structure + findings (PII too, if deep scan)
//   scoring                       → Rubric.assess() per file: a numeric score and per-criterion
//                                   pass/fail; Rubric.aggregate() for the estate summary
//   done
//
// So the scan DOES score. (An earlier version of this comment claimed "Discover … does NOT
// assess conformance", which the code contradicts.) What the scan does not do is decide
// conformance at a chosen level — that is the Assess step, which sets `assessed_at` and filters
// the already-computed findings by level, in the browser, in milliseconds. And the scan NEVER
// remediates.
//
// Enforced by phaseNarration.test.js, which fails on cross-step vocabulary and on any narration
// derived from elapsed time.

// phase (from api/scanner.py's progress callback) → what is genuinely happening.
export const SCAN_PHASE_LINES = {
  queued: 'Waiting for a worker to pick up the scan…',
  connecting: 'Connecting to the source…',
  discovering: 'Listing the documents in this source…',
  reading: 'Downloading each document…',
  analysing: 'Extracting text, images and document structure…',
  scoring: 'Scoring each document against the rubric…',
  done: 'Finished.',
}

// The deep (PII) scan runs inside the `analysing` phase, so it may only be named there, and
// only when it is switched on. Naming it anywhere else claims work that isn't running.
const ANALYSING_DEEP = 'Extracting document structure and deep-scanning for sensitive data (PII)…'

export function scanPhaseLine(phase, { deepScan = false } = {}) {
  if (phase === 'analysing' && deepScan) return ANALYSING_DEEP
  return SCAN_PHASE_LINES[phase] ?? null   // an unknown phase narrates nothing, never a guess
}

export const ASSESS_LINES = [
  'Selecting the findings that block this conformance level…',
  'Counting blocking failures per document…',
  'Marking each document conformant or failing…',
]

export const assessLine = (i) => ASSESS_LINES[i % ASSESS_LINES.length]

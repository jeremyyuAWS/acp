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
//
// A LINE CAN BE TRUE ABOUT THE JOB AND STILL WRONG WHERE IT IS RENDERED. `analysing`'s line
// ("Extracting text, images and document structure…") is an accurate description of what the
// engines do — and it was being shown on step 1, Discover, whose own subtitle is
// "inventory · classify" and whose panel body says the agent "crawls metadata, proposes a
// classification & a lifecycle action". One screen, two incompatible accounts of the same step.
//
// The words were not the defect. The PHASE was on the wrong step. ADR 0020 draws the line the
// product is sold on, and draws it precisely:
//
//   Discover answers "what is this?"   — identity and inventory metadata.
//   Assess   answers "what's wrong with it?" — every WCAG success-criterion evaluation.
//
// `analysing` is `_analyse_one` (api/scanner.py) — the .NET OpenXML analysers, the PDF/HTML
// analysers, OCR images-of-text, sensory/language text checks, contrast and headings. That is
// the second question, not the first. ADR 0020 stages 3+4 SHIPPED, so in the deployed default
// (`ACP_DEFER_ANALYSIS_TO_ASSESS=1`, deploy/public/deploy.sh:360) the phase does not even run
// under the Discover trigger any more: Discover lists only, and the download+analyse fan-out is
// `scan_assess`, fired by POST /scans/{sid}/assess. The code default is 0 (api/handlers.py:31),
// so on a local run the analysis DOES still happen inside the Discover-triggered scan — which
// is why the phase cannot simply be deleted from Discover, and why the honest line has to be
// true under both models.
//
// So: PHASE_STEP records which step OWNS each phase's work, and a step rendering a phase it does
// not own may say THAT the work is running and where its output lands — never narrate the work
// as if it were its own. phaseNarration.test.js pins the assignment, so a phase added later
// cannot silently land on the wrong step.

// phase (from api/scanner.py's progress callback) → what is genuinely happening.
export const SCAN_PHASE_LINES = {
  queued: 'Waiting for a worker to pick up the scan…',
  connecting: 'Connecting to the source…',
  discovering: 'Listing the documents in this source…',
  reading: 'Downloading each document…',
  analysing: 'Extracting text, images and document structure…',
  scoring: 'Scoring each document from what was found…',
  done: 'Finished.',
}

// Which workflow step's work each phase IS, by ADR 0020's dividing question. 'any' is for the
// phases that answer neither question — plumbing that serves whichever step triggered the job,
// and so is honest to narrate verbatim wherever it is rendered.
//
//   discovering → lists the estate. "What do we have?" — Discover's own work.
//   connecting/reading/queued/done → connecting to a source, downloading bytes, waiting on a
//     worker, finishing. Under ADR 0020 §B the download serves Discover or Assess depending on
//     the flag, and none of it is a claim about a document's conformance.
//   analysing/scoring → the detector suite and Rubric.assess()'s score + per-criterion
//     pass/fail. "What's wrong with it?" — Assess's work, wherever the job happens to run it.
export const PHASE_STEP = {
  queued: 'any',
  connecting: 'any',
  discovering: 'discover',
  reading: 'any',
  analysing: 'assess',
  scoring: 'assess',
  done: 'any',
}

// The steps that own scan phases. Derived, not hand-listed, so adding an owner to PHASE_STEP is
// enough — a caller can ask whether the view it is rendering in is a step that owns phases
// without keeping its own copy of the list. A view that is not a step (Overview, Integrations)
// has no step vocabulary to be scoped to and narrates the job.
export const NARRATION_STEPS = new Set(Object.values(PHASE_STEP).filter((s) => s !== 'any'))

// What a step may say while a phase it does NOT own is running. Keyed by the step doing the
// rendering, then the phase. A pair with no entry here narrates nothing — silence beats a
// plausible sentence, the same rule an unknown phase already follows.
//
// Discover is allowed to name the PII deep scan, and only the PII deep scan, because sensitive
// data is an ADR 0006 property of the artifact — "what is this?" — not a WCAG criterion. It is
// not allowed to describe the extraction, which is the whole defect this replaces.
// Every (phase, step) pair gets a line. Silence is the rule for an UNKNOWN phase — there is
// nothing to say about work we cannot name — but a known phase on a known step is work we can
// name, and a blank line under a live spinner is its own kind of dishonesty. Pinned by the test.
const CROSS_STEP = {
  discover: {
    analysing: 'The accessibility assessment has started — findings appear on the Assess step…',
    scoring: 'The accessibility assessment is scoring each document — scores appear on the Assess step…',
  },
  assess: {
    // Deliberately not "Listing the documents in this source…": on Assess that would be false.
    // `queuedProgress` (App.jsx) reports `discovering` whenever the run's file count is still 0,
    // which during a deferred Assess run means the fan-out is being rebuilt from an inventory
    // that was listed long ago — not that the source is being listed again.
    discovering: 'Waiting for the document list…',
  },
}
const CROSS_STEP_DEEP = {
  discover: {
    analysing: 'Deep-scanning for sensitive data (PII) — the accessibility assessment has started; findings appear on the Assess step…',
  },
}

// The deep (PII) scan runs inside the `analysing` phase, so it may only be named there, and
// only when it is switched on. Naming it anywhere else claims work that isn't running.
const ANALYSING_DEEP = 'Extracting document structure and deep-scanning for sensitive data (PII)…'

// `step` is the step doing the rendering. Omit it to narrate the JOB rather than a step — what
// the top bar and Monitor do, since neither claims to be a pipeline step.
export function scanPhaseLine(phase, { deepScan = false, step = null } = {}) {
  const owner = PHASE_STEP[phase]
  if (step && owner && owner !== 'any' && owner !== step) {
    const deep = deepScan ? CROSS_STEP_DEEP[step]?.[phase] : null
    return deep ?? CROSS_STEP[step]?.[phase] ?? null
  }
  if (phase === 'analysing' && deepScan) return ANALYSING_DEEP
  return SCAN_PHASE_LINES[phase] ?? null   // an unknown phase narrates nothing, never a guess
}

// The CONCRETE line, under the narration: which document, which criterion, what action.
//
// scanPhaseLine narrates the PHASE — true, general, and identical for the whole forty seconds a
// long document spends in `analysing`. The complaint it does not answer is "is it on MY file
// yet?", and neither does a percentage. `api/activity.py` builds the specific line
// ("benefits.docx · 1.1.1 Non-text Content · describing images") and both the scan progress
// payload and the remediation-status poll now carry it.
//
// SAME RULE AS THE NARRATION: never fabricate. This renders what the backend reported and
// nothing else — no interpolation, no elapsed-time cycling, no "probably still on file 3 of 9".
// A payload with no activity renders no line, which is the honest state and is why every branch
// here ends in null rather than in a plausible sentence.
//
// The backend string is preferred over reassembling the parts in the browser, so the phrasing
// lives in one place; `current` is the fallback for a payload predating the activity field,
// where the filename alone is still more use than the phase alone.
export function activityLine(progress) {
  if (!progress || typeof progress !== 'object') return null
  const a = progress.activity
  if (typeof a === 'string' && a.trim()) return a.trim()
  // remediation-status nests it as an object; the scan payload sends the flat string.
  if (a && typeof a === 'object' && typeof a.text === 'string' && a.text.trim()) return a.text.trim()
  const cur = progress.current
  return typeof cur === 'string' && cur.trim() ? cur.trim() : null
}

export const ASSESS_LINES = [
  'Selecting the findings that block this conformance level…',
  'Counting blocking failures per document…',
  'Marking each document conformant or failing…',
]

export const assessLine = (i) => ASSESS_LINES[i % ASSESS_LINES.length]

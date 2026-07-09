// The one-line "still working" narration under each step's progress bar.
//
// Rule: a step narrates ONLY the work it actually performs, and only work it performs.
// These lines are the most-read text in the product — they run while the user is staring
// at a spinner with nothing else to do — and a line that claims work the step isn't doing
// is a lie the user has no way to check.
//
// Discover runs the engine and collects findings. It does NOT assess conformance and it
// NEVER remediates. Announcing WCAG criteria here made the scan look like it had already
// assessed (and even remediated) the estate.
//
// Assess re-opens nothing. The engine produced the findings during the scan; this step
// evaluates them against the chosen conformance level, in the browser, in milliseconds.
// It previously narrated "Opening OOXML package…", "Extracting PDF tag tree…" and
// "Transcribing with Whisper…" — none of which happen here, and Whisper is not called at
// all. The elapsed time is a deliberate legibility floor, not work.
//
// Enforced by phaseNarration.test.js, which fails on cross-step vocabulary.

export const DISCOVER_LINES = [
  'Downloading and parsing each document…',
  'Extracting text, images and document structure…',
  'Reading document metadata and properties…',
  'Running deep scan for sensitive data (PII)…',
  'Collecting findings for the Assess step…',
]

export const ASSESS_LINES = [
  'Selecting the findings that block this conformance level…',
  'Counting blocking failures per document…',
  'Marking each document conformant or failing…',
]

// When PII (deep) scan is off, drop the PII line so the narration never claims work that
// isn't running — the rest are steps every scan performs.
export function discoverLine(elapsed, deepScan = false) {
  const lines = deepScan ? DISCOVER_LINES : DISCOVER_LINES.filter((l) => !/sensitive data \(PII\)/i.test(l))
  return lines[Math.floor(elapsed / 5) % lines.length]
}

export const assessLine = (i) => ASSESS_LINES[i % ASSESS_LINES.length]

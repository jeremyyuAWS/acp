// Effort is a PLANNING HEURISTIC, never a measurement.
//
// sim.js `recommendFor` multiplies the finding count by fixed constants — roughly 35 min per
// finding by hand, ~1 min per finding automated, and a per-severity table for assisted review.
// Nothing times the real work. So effort:
//
//   * renders as "est." wherever it appears, and carries EFFORT_BASIS as its tooltip, so it
//     can never be read as an observed number;
//   * appears in NO certification report — that is a conformance artifact a customer relies
//     on, and it must not carry a quantified savings claim nobody measured.
//
// Real reviewer time IS captured (hitl_events.review_ms, client-measured from card-open to
// decision). Grounding these numbers on it is a separate, worthwhile job.
//
// Enforced by effortHonesty.test.js.

export const EFFORT_BASIS =
  'Planning estimate only — a fixed per-finding heuristic, not a measurement. No timing data informs it.'

export const fmtEffort = (m) =>
  m == null ? '—' : m === 0 ? 'no work' : m >= 90 ? `est. ${(m / 60).toFixed(1)} hrs` : `est. ${Math.round(m)} min`

// Per-finding planning constants (minutes) — the same fixed heuristic sim.js's recommendFor uses
// (~a minute to run an automated fix, ~35 to do one by hand), surfaced here so a surface can
// estimate effort from a capability-grounded finding split WITHOUT the SIM-only f.rec (which is 0
// on real scans). Still a planning estimate, never a measurement — always rendered via fmtEffort
// ("est.") with EFFORT_BASIS as the tooltip.
export const EFFORT_MIN = { auto: 1, person: 35 }
export const estimateEffortMin = ({ auto = 0, person = 0 }) => auto * EFFORT_MIN.auto + person * EFFORT_MIN.person

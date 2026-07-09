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

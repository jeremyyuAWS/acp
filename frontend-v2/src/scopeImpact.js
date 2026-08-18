// The live "population funnel" behind the Assess scope builder.
//
// A flat "1,386 eligible" number hides the two decisions that shaped it: how many discovered files
// the platform can assess AT ALL, and how many the operator's document-type selection then keeps.
// This turns that one number into the narrowing the user actually made — Discovered → Eligible for
// the selected criteria → In the selected document types — with each DROP explained, so a reviewer
// can see (and defend) exactly what this run will and won't cover.
//
// HONESTY (ADR 0016): every count here comes straight from the eligibility aggregate the scope
// screen already fetches (`discovered`, `eligible`, `by_format`). It does NOT model the lifecycle-
// exclusion or changed-since-last-assessment stages — those need aggregates this screen doesn't
// load (count_lifecycle_by_status, the inventory diff) and will be a later increment. Nothing here
// is fabricated: a stage we can't back is simply absent, not guessed.

const sumFormats = (byFormat = {}, keep = null) =>
  Object.entries(byFormat).reduce((n, [f, v]) => n + ((keep == null || keep.has(f)) ? (v || 0) : 0), 0)

/** Compose the scope funnel from the live eligibility aggregate + the selected document formats.
 *  `elig` is `{discovered, eligible, by_format}` (fetchEligibility); `formats` is a Set of ticked
 *  doc-types. Returns null when there is no eligibility data yet. */
export function scopeImpact(elig, formats = new Set()) {
  if (!elig) return null
  const byFormat = elig.by_format || {}
  const discovered = elig.discovered || 0
  // Files whose format is reached by at least one selected criterion (has an assessment lane).
  const eligible = Number.isFinite(elig.eligible) ? elig.eligible : sumFormats(byFormat)
  // …narrowed to the document types the operator actually ticked.
  const inScope = sumFormats(byFormat, formats)

  const noMethod = Math.max(0, discovered - eligible)   // unsupported type, or no lane for any picked criterion
  const deselected = Math.max(0, eligible - inScope)    // eligible, but in a format the operator excluded

  const funnel = [
    { key: 'discovered', label: 'Discovered', count: discovered, drop: 0,
      note: 'Every file ACP inventoried across the connected sources' },
    { key: 'eligible', label: 'Eligible for the selected criteria', count: eligible, drop: noMethod,
      note: noMethod ? `${noMethod.toLocaleString()} have no assessment method for the selected criteria` : 'All discovered files can be assessed by the selected criteria' },
    { key: 'inscope', label: 'In your selected document types', count: inScope, drop: deselected,
      note: deselected ? `${deselected.toLocaleString()} eligible file${deselected === 1 ? '' : 's'} in document types you didn't select` : 'All eligible files are in your selected types' },
  ]

  const excluded = [
    noMethod > 0 && { key: 'nomethod', label: 'Inventory only — no assessment method', count: noMethod,
      why: 'Unsupported file type, or no lane for any selected criterion' },
    deselected > 0 && { key: 'deselected', label: 'Excluded by your document-type selection', count: deselected,
      why: "Eligible, but in a format you didn't tick" },
  ].filter(Boolean)

  return {
    discovered, eligible, inScope, noMethod, deselected,
    pct: discovered ? Math.round((inScope / discovered) * 100) : 0,
    funnel, excluded,
  }
}

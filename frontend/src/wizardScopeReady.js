// An empty selection means two opposite things, and the screen was saying the reassuring one.
//
// From the New-scan wizard on 2026-08-20, all true at once:
//
//   · "Specific folders" is the selected mode
//   · CURRENT SCOPE reads "Nothing selected — this scan covers all of OneDrive."
//   · the footer reads "Entire source · 4 formats · Core 17"
//   · Continue is enabled
//
// So the user states "assess only these folders", picks none (often because the folder list
// FAILED to load — see the Graph 400 in #501), and the run they authorise is the whole estate.
// Nothing lies: an empty `folders` list really does scan everything, because that is the correct
// reading on a SOURCE CARD, where "no restriction" is the connection's default. The wizard then
// borrowed that reading for a mode whose entire meaning is a restriction.
//
// Same family as the false-verdict fixes (#479, #483, #491): a silent fallback to the reassuring
// interpretation of missing data. The difference is that this one spends money and time on
// thousands of documents nobody asked for.
//
// THE RULE: empty means "everything" only where the user never claimed to be narrowing. Once
// "Specific folders" is chosen, empty is INCOMPLETE — not everything, not nothing — and the
// primary action is unavailable until it is resolved. Never reinterpret it.

/**
 * Has the user chosen to narrow, but not yet said to what?
 *
 * Exclusions alone do not count: "exclude Archive, include nothing" still names no scope to
 * subtract from, and would fall through to the whole source exactly as an empty list does.
 */
export function scopeIncomplete(scopeMode, folders) {
  return scopeMode === 'some' && (folders || []).length === 0
}

/** The line shown in place of "…this scan covers all of OneDrive." Names the fix, not the state. */
export const INCOMPLETE_LINE = 'Select at least one folder to continue.'

/**
 * The locations half of the footer summary.
 *
 * The footer printed "Entire source" for an empty list whatever the mode, which is how it came to
 * contradict the mode selector two inches above it. Three states, said apart:
 *   · narrowing, nothing chosen  → the incomplete state, never "Entire source"
 *   · narrowing, folders chosen  → the count, plus exclusions
 *   · not narrowing              → entire source, which is the honest answer there
 */
export function scopeFooterPart(scopeMode, folders, excluded) {
  const inc = (folders || []).length
  const exc = (excluded || []).length
  if (scopeIncomplete(scopeMode, folders)) return 'No folders selected'
  if (inc === 0) return 'Entire source'
  return `${inc} folder${inc === 1 ? '' : 's'}${exc ? ` · ${exc} excluded` : ''}`
}

/**
 * May the wizard advance past the locations step?
 *
 * Returns a REASON rather than a boolean so the disabled control can say why — a dead Continue
 * button with no explanation is its own defect, and the reason is the thing the user has to act on.
 * `null` means ready.
 */
export function blockedReason(scopeMode, folders) {
  return scopeIncomplete(scopeMode, folders) ? INCOMPLETE_LINE : null
}

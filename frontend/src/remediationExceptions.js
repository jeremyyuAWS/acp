// The exception region's own logic, kept out of the component so it can be tested without a DOM.
//
// THE SERVER DECIDES WHAT IS ACTIONABLE. Every function here reads `action_enabled`,
// `action_reason` and `action_code` off the row the server sent; none of them re-derives
// eligibility from a digest, a timestamp or a provider name. api/remediation_exceptions.py made
// that decision against the database, and a second implementation in the browser would eventually
// disagree with it — at which point the panel offers a button the server refuses, or hides one it
// would have honoured. The same rule remediationSnapshot.js follows for run state, applied to an
// action that writes to a customer's estate.

export const GROUP_ORDER = ['document_failure', 'delivery_failure', 'authoring_required',
  'review_required', 'verification_failure']

// How many documents a group lists before it collapses to a count. Exceptions are meant to be
// worked, not scrolled: a group of 147 undelivered documents is one decision ("retry all of
// these"), and rendering 147 rows to support it buries the four other groups underneath.
export const VISIBLE_PER_GROUP = 5

export function groupSummary(group) {
  const total = group?.documents || 0
  const actionable = group?.actionable || 0
  const noun = `${total} document${total === 1 ? '' : 's'}`
  if (!group?.action) return noun
  if (actionable === total) return noun
  return `${noun} · ${actionable} can be retried`
}

// The documents a group action would actually touch: the ones ON SCREEN that the server marked
// actionable, intersected with the user's selection when they have made one.
//
// VISIBILITY IS PART OF THE CONTRACT, not a rendering detail. "Retry all" over a collapsed group
// would act on rows the user cannot see and did not evaluate; scoping it to what is rendered is
// what makes the button's label true. Expanding the group widens the action, which is the
// behaviour a user expects from an expander and the reason the count is in the label.
export function eligibleFiles(group, { selected = null, expanded = false } = {}) {
  const items = visibleItems(group, expanded)
  const enabled = items.filter((item) => item.action_enabled).map((item) => item.file)
  if (!selected || selected.size === 0) return enabled
  return enabled.filter((file) => selected.has(file))
}

export function visibleItems(group, expanded = false) {
  const items = Array.isArray(group?.items) ? group.items : []
  return expanded ? items : items.slice(0, VISIBLE_PER_GROUP)
}

// A selection carried across a live update keeps only the files still on screen and still
// actionable. PRD §12 asks that a live update never move focus or lose the user's place; a
// selection that silently retains a document the server has since delivered would send a retry
// for it, which is worse than losing the tick.
export function reconcileSelection(selected, groups) {
  const live = new Set()
  for (const group of groups || []) {
    for (const item of group.items || []) {
      if (item.action_enabled) live.add(item.file)
    }
  }
  const next = new Set()
  for (const file of selected || []) if (live.has(file)) next.add(file)
  return next
}

// One sentence about what a group action actually did. Reads the server's own summary when it has
// one, because the server counted the outcomes; the fallback exists only for a response shape
// this client does not recognise, and it still never claims success it cannot see.
export function outcomeMessage(result) {
  if (!result) return null
  if (typeof result.summary === 'string' && result.summary) {
    return result.complete_success ? result.summary : `${result.summary}. Review the details below.`
  }
  return 'The action completed with an unrecognised result. Refresh to see the current state.'
}

// Per-document outcomes, in the order the server reported them, for the detail list under a group
// that did not entirely succeed. A wholly successful action returns none: the counts already said
// so, and repeating twelve "started" rows under "12 delivery operations started" is noise.
export function outcomeDetails(result) {
  if (!result || result.complete_success) return []
  return (result.results || []).filter((row) => row.outcome !== 'started')
}

export const OUTCOME_LABELS = {
  started: 'Started', duplicate: 'Already in progress', refused: 'Refused',
  failed: 'Could not start',
}

export function outcomeTone(outcome) {
  if (outcome === 'started') return 'success'
  if (outcome === 'duplicate') return 'neutral'
  return outcome === 'refused' ? 'attention' : 'error'
}

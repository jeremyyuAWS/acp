// Search for the AI Work Inbox (Remediate). The inbox can hold dozens of EvidenceCards; a
// reviewer navigating it needs to jump to "the docx link-purpose ones" or "everything in
// contract.pdf" without scrolling the whole queue. This is the one piece with real logic, so it
// lives here as a pure function the tests can exercise directly rather than through a full mount.
//
// The haystack deliberately spans the three things a reviewer searches by — the FILENAME, the
// WCAG criterion (its number AND its name), and the AI's recommendation text — because any of the
// three is a plausible thing to have in mind. Matching is token-AND and substring: every
// whitespace-separated token must appear somewhere, so "docx 2.4.4" narrows to docx items on
// 2.4.4 and order does not matter. Empty query matches everything (the no-filter state).

// Fields carried on the UI item (dbItemToUi) and on its raw hitl_queue row (_raw) that a reviewer
// might search by. Kept explicit rather than "stringify the whole object" so a new internal field
// can't silently start matching — the searchable surface is a decision, not an accident.
const UI_FIELDS = ['file', 'rule', 'title', 'meta', 'before', 'severity', 'ruleId']
const RAW_FIELDS = ['file', 'rule_id', 'rule_name', 'recommendation', 'proposed_value', 'approved_value']

export function reviewHaystack(item) {
  if (!item) return ''
  const parts = []
  for (const k of UI_FIELDS) {
    const v = item[k]
    if (typeof v === 'string' && v) parts.push(v)
  }
  const raw = item._raw
  if (raw && typeof raw === 'object') {
    for (const k of RAW_FIELDS) {
      const v = raw[k]
      if (typeof v === 'string' && v) parts.push(v)
    }
  }
  return parts.join(' ').toLowerCase()
}

export function matchesReviewQuery(item, query) {
  const q = (query || '').trim().toLowerCase()
  if (!q) return true
  const hay = reviewHaystack(item)
  return q.split(/\s+/).every((tok) => hay.includes(tok))
}

// Convenience for the component: filter a queue, preserving order (priority is already baked into
// the queue's order, so search must not reshuffle it).
export function filterReviewQueue(queue, query) {
  const q = (query || '').trim()
  if (!q) return queue
  return (queue || []).filter((item) => matchesReviewQuery(item, q))
}

// The approval queue: AI-drafted fixes waiting for a person, and the rows that only look like them.
//
// WHY DRAFTS LIVE ON THE REMEDIATION SCREEN AT ALL. Generating a candidate value is remediation
// work, not assessment work — it changes what the document will say. The assessment screens were
// stripped of drafts for exactly that reason, and this is where they went. The consequence is that
// this module is the only place a drafted value is ever offered for approval, so it is also the
// only place the "a draft is not a fix" rule can be broken.
//
// THE SPLIT THAT MATTERS, AND IT IS NOT pending/reviewed. A queue row is created per (document,
// criterion) whenever a run defers that criterion to a human. Some of those rows carry a model's
// actual draft; some carry nothing at all, because no draft could be produced. Both arrive in the
// same list, from the same endpoint, looking identical. A row with no draft is NOT an approval —
// there is nothing to approve — and rendering it beside a real one with an Approve button asks a
// reviewer to sign off on the absence of a suggestion.
//
// This has bitten before, in the other direction: the queue card used to fall back to a canned
// template ("AI-generated alt text added — confirm or reword") whenever no proposal existed, so
// every image in every document rendered an identical "draft" whether or not a model had said
// anything. There is no template fallback anywhere in this module. `draft === null` means nothing
// was drafted, and the screen says exactly that.
//
// A ROW IS NOT ONE DRAFT. `proposals` holds one entry per image / link / field the criterion failed
// on, and approving the row accepts every one of them. `draftCount` is carried out of here so the
// screen can say so before somebody presses a button that writes eight alt texts.
import { proposalsOf, firstProposed, firstBefore, firstThumb, firstRationale,
         firstSource, pageOf } from './reviewCard.js'

// A decision has been recorded on these; they are no longer waiting for anybody. Everything else —
// 'pending', null, a status the backend has not invented yet — is treated as waiting, because the
// failure mode of the other default is a queue that quietly hides work.
export const RESOLVED_STATUSES = new Set(['approved', 'rejected', 'skipped'])

/** 'SC_1_1_1' / 'WCAG_1_1_1' / '1.1.1' → '1.1.1'. The queue's `rule_id` arrives in all three. */
export const scOfRuleId = (ruleId) =>
  String(ruleId || '').replace(/^(WCAG_?|SC_)/, '').replace(/_/g, '.')

/** One queue row, normalized. Nothing is invented: every field is null where the row is silent. */
export function approvalItem(row) {
  if (!row) return null
  const proposals = proposalsOf(row)
  const draft = firstProposed(row)
  return {
    id: row.id,
    file: row.file || '',
    sc: scOfRuleId(row.rule_id),
    ruleName: row.rule_name || null,
    // The location, per the analysers. Null when they could not attribute one — the card then
    // shows no page rather than a wrong one.
    page: pageOf(row),
    pages: row.pages || null,
    findingCount: typeof row.finding_count === 'number' ? row.finding_count : null,
    // What the model actually wrote for THIS document. Null means nothing was drafted.
    draft,
    // The passage the fix would replace, when a proposal named one.
    before: firstBefore(row),
    rationale: firstRationale(row),
    thumb: firstThumb(row),
    source: firstSource(row),
    // True only where a deterministic fix was applied AND verifiably cleared on the re-scan of the
    // corrected bytes. It is evidence about the fix, never a reason to skip the approval.
    validated: !!row.validated,
    // How many values one Approve press accepts. See the note at the top of this file.
    draftCount: proposals.length,
    proposals,
  }
}

const bySc = (a, b) => a.file.localeCompare(b.file)
  || a.sc.localeCompare(b.sc, undefined, { numeric: true })
  || String(a.id).localeCompare(String(b.id))

/**
 * The queue, split three ways.
 *
 * Returns `null` when nothing has been loaded — an absent list is not an empty queue, and "0
 * drafts awaiting approval" over a fetch that never returned is a lie the reader cannot detect.
 *
 * @param rows  hitl_queue rows as GET /hitl/queue returns them
 * @returns {{awaiting, undrafted, resolved, total}} — `awaiting` is the only set that may be
 *          approved. The three counts sum to `total`, and the screen prints that.
 */
export function approvalQueue(rows) {
  if (!Array.isArray(rows)) return null
  const awaiting = []
  const undrafted = []
  let resolved = 0
  for (const row of rows) {
    if (RESOLVED_STATUSES.has(row?.status)) { resolved++; continue }
    const item = approvalItem(row)
    if (!item) continue
    ;(item.draft === null || item.draft === '' ? undrafted : awaiting).push(item)
  }
  awaiting.sort(bySc)
  undrafted.sort(bySc)
  return { awaiting, undrafted, resolved, total: rows.length }
}

/**
 * Does the queue's own arithmetic hold? Printed under the list for the same reason the work
 * partition prints its identity: a reader who can see three numbers and a total can check it.
 */
export function reconcileQueue(q) {
  if (!q) return null
  const sum = q.awaiting.length + q.undrafted.length + q.resolved
  return {
    ok: sum === q.total,
    line: `${q.awaiting.length} awaiting approval + ${q.undrafted.length} with no draft + `
        + `${q.resolved} already decided = ${q.total} queue item${q.total === 1 ? '' : 's'}`,
    sum,
  }
}

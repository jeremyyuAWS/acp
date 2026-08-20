// Plain-language vocabulary for the Discover "Lifecycle rules" step.
//
// This module holds the pure part of that screen: the condition templates a person actually
// picks from, the mapping between those and the (field, op) pairs api/disposition.py validates,
// and the sentence generator that restates a stored rule in the reader's words rather than the
// schema's. It is separated from DispositionRules.jsx so the wording — which is the safety
// mechanism on this screen — can be asserted directly, without a DOM.
//
// THE VOCABULARY RULE. A lifecycle rule running in Discover writes a RECOMMENDATION and nothing
// else: api/handlers._evaluate_discover_lifecycle_rules sets lifecycle_status to
// "Archive Candidate" or "Delete Candidate" and writes an audit row. It never moves, trashes,
// renames or opens a file — the Drive action lives behind a separate enable + execute + approve
// path (api/routes/disposition.py). So nothing in here may say a file WAS archived or deleted.
// The permitted words are: tagged for review, recommendation, candidate, needs your decision.
// This is the screen where a person writes a rule that SOUNDS destructive and is not, so the
// distinction has to be carried by the copy at the point the choice is made.
//
// And when a recommendation is eventually acted on, "delete" is Drive TRASH — recoverable — never
// files().delete(). See disposition.execute_action, which has no permanent-delete path at all.

export const ARCHIVE = 'archive'
export const DELETE = 'delete'

/** The two lifecycle actions this editor offers. `action` is what the backend stores. */
export const ACTIONS = [
  {
    action: ARCHIVE,
    label: 'Recommend archive',
    tag: 'recommend archive',
    // What the rule does to a matching file, in the sentence's grammar.
    outcome: 'tagged for archive review',
    candidate: 'Archive Candidate',
    safety: 'Matching files are tagged as archive candidates and excluded from Assess by default. '
          + 'Nothing is moved — the tag is a recommendation that still needs your decision.',
  },
  {
    action: DELETE,
    label: 'Recommend deletion',
    tag: 'recommend deletion',
    outcome: 'tagged for deletion review',
    candidate: 'Delete Candidate',
    safety: 'Matching files are tagged as deletion candidates. Nothing is trashed or deleted here. '
          + 'If you later act on a recommendation, deletion means Drive trash — recoverable, '
          + 'never a permanent delete.',
  },
]

/** Actions this editor owns. A 'tag'/'move'/'rename' policy made elsewhere is not shown here. */
export const LIFECYCLE_ACTIONS = new Set(ACTIONS.map((a) => a.action))
export const actionSpec = (action) => ACTIONS.find((a) => a.action === action) || ACTIONS[0]

// ── Conditions ───────────────────────────────────────────────────────────────
// Each entry is one field in the builder. `field`/`op` are exactly what
// disposition.validate_match accepts; nothing here can express a condition the backend
// would reject. Conditions are ANDed (disposition.matches requires every one).
export const CONDITIONS = [
  {
    key: 'folder',
    label: 'Folder path starts with',
    field: 'parent_folder',
    op: 'prefix',
    kind: 'text',
    placeholder: 'e.g. Finance/2019/',
    // Reads as a place, so it sits first in the sentence and needs no "and" after it.
    positional: true,
    lead: 'under ',
  },
  {
    key: 'modifiedBefore',
    label: 'Last modified before',
    field: 'modified_at',
    op: 'before',
    kind: 'date',
    placeholder: 'YYYY-MM-DD',
    lead: 'last modified before ',
  },
  {
    key: 'notModifiedDays',
    label: 'Not modified in the last',
    field: 'modified_age_days',
    op: 'gt',
    kind: 'number',
    unit: 'days',
    placeholder: 'e.g. 1095',
    lead: 'not modified in the last ',
  },
]

const BY_FIELD_OP = new Map(CONDITIONS.map((c) => [`${c.field}:${c.op}`, c]))

// Conditions a rule may already carry from elsewhere (the older editor, or the API directly).
// Rendering them as "modified age days gt 1095" would put the schema back in front of the reader,
// so every field the backend allows gets a phrase here even when the builder cannot create it.
const EXTRA_PHRASES = {
  'path:contains': { lead: 'whose path contains ' },
  'created_at:before': { lead: 'created before ', date: true },
  'age_days:gt': { lead: 'older than ', unit: 'days' },
  'department:eq': { lead: 'owned by the ', unit: 'department' },
  'owner:eq': { lead: 'owned by ' },
  'source:eq': { lead: 'in ' },
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2021-01-01" → "1 Jan 2021". Anything unparseable comes back unchanged rather than as a
 *  guess — a date we cannot read is not a date we may restate. */
export function formatRuleDate(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value ?? ''))
  if (!m) return String(value ?? '')
  const month = Number(m[2])
  if (month < 1 || month > 12) return String(value)
  return `${Number(m[3])} ${MONTHS[month - 1]} ${m[1]}`
}

/** One stored condition → { lead, value, positional } in reader's words, or null if unreadable. */
function clauseFor(cond) {
  if (!cond || !cond.field || !cond.op) return null
  const key = `${cond.field}:${cond.op}`
  const tpl = BY_FIELD_OP.get(key)
  const extra = EXTRA_PHRASES[key]
  const raw = cond.value
  if (tpl) {
    const value = tpl.kind === 'date' ? formatRuleDate(raw)
      : tpl.unit ? `${raw} ${tpl.unit}`
      : String(raw ?? '')
    return { lead: tpl.lead, value, positional: !!tpl.positional }
  }
  if (extra) {
    const value = extra.date ? formatRuleDate(raw) : extra.unit ? `${raw} ${extra.unit}` : String(raw ?? '')
    return { lead: extra.lead, value, positional: false }
  }
  // Last resort: still no schema punctuation, but no invented phrasing either.
  return { lead: `${String(cond.field).replaceAll('_', ' ')} ${cond.op} `, value: String(raw ?? ''), positional: false }
}

/** Parse the `match` column, which is stored as a JSON string. Never throws — a legacy or
 *  corrupt row yields [] and the caller says so, rather than the component failing to mount. */
export function parseMatch(match) {
  if (Array.isArray(match)) return match
  try {
    const parsed = JSON.parse(match || '[]')
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

/**
 * The rule, as a sentence, in segments so the component can bold the parts a reader scans for.
 * Returns [{ t, b }] where `b` marks bold. Example:
 *
 *   Files under **Clinical Guidelines/** last modified before **1 Jan 2021**
 *   will be **tagged for archive review**.
 *
 * A rule with NO conditions matches every file in scope. That is stated in the same breath and in
 * bold rather than left as an empty clause the eye slides over.
 */
export function ruleSentenceParts(match, action) {
  const spec = actionSpec(action)
  const clauses = parseMatch(match).map(clauseFor).filter(Boolean)
  // The folder clause reads first whatever order it was stored in.
  const pi = clauses.findIndex((c) => c.positional)
  const ordered = pi > 0 ? [clauses[pi], ...clauses.filter((_, i) => i !== pi)] : clauses

  const out = [{ t: 'Files' }]
  if (!ordered.length) {
    out.push({ t: ' ' }, { t: 'in every folder in scope', b: true })
  } else {
    ordered.forEach((c, i) => {
      const sep = i === 0 ? ' ' : ordered[i - 1].positional ? ' ' : ' and '
      out.push({ t: sep + c.lead }, { t: c.value, b: true })
    })
  }
  out.push({ t: ' will be ' }, { t: spec.outcome, b: true }, { t: '.' })
  return out
}

/** The same sentence as a plain string — for titles, aria labels and source-level assertions. */
export const ruleSentenceText = (match, action) =>
  ruleSentenceParts(match, action).map((p) => p.t).join('')

/**
 * How the preview count is stated. `null` means NOT YET ASKED, and it must never be rendered as a
 * measured zero — an unanswered question and "nothing matched" are different facts, and printing
 * "0 files" for the first is the error this whole screen is built to avoid.
 */
export function matchCountText(n) {
  if (n == null) return 'Preview to see how many files match.'
  if (n === 0) return 'Matches none of the files discovered so far.'
  if (n === 1) return 'Matches about 1 file.'
  return `Matches about ${Number(n).toLocaleString()} files.`
}

// ── Draft → backend payload ──────────────────────────────────────────────────

/** A blank builder draft: one value slot per condition, all empty. */
export const emptyDraft = () => ({
  name: '',
  action: ARCHIVE,
  values: Object.fromEntries(CONDITIONS.map((c) => [c.key, ''])),
})

/**
 * Draft → the `match` array the API takes. Blank fields are omitted (they are not conditions),
 * numeric fields are coerced to numbers because disposition._OPS['gt'] compares with `>` and a
 * string would compare lexically. Order follows CONDITIONS so the stored rule reads the same way
 * it was typed.
 */
export function draftToMatch(draft) {
  const values = (draft && draft.values) || {}
  return CONDITIONS.flatMap((c) => {
    const raw = values[c.key]
    if (raw === '' || raw == null) return []
    return [{ field: c.field, op: c.op, value: c.kind === 'number' ? Number(raw) : String(raw) }]
  })
}

/**
 * Why this draft cannot be submitted yet, or '' when it can.
 *
 * The condition-count check is the load-bearing one: a rule with no conditions matches EVERY file
 * in scope, so an accidental empty rule would tag the whole estate for review. It is refused here
 * rather than explained after the fact.
 */
export function draftProblem(draft) {
  if (!draft || !String(draft.name || '').trim()) return 'Give the rule a name.'
  const match = draftToMatch(draft)
  if (!match.length) return 'Add at least one condition — a rule with none would match every file in scope.'
  for (const c of CONDITIONS) {
    const raw = (draft.values || {})[c.key]
    if (raw === '' || raw == null) continue
    if (c.kind === 'number' && !(Number(raw) > 0)) return `“${c.label}” must be a number of days greater than zero.`
    if (c.kind === 'date' && !/^\d{4}-\d{2}-\d{2}$/.test(String(raw))) return `“${c.label}” must be a date, as YYYY-MM-DD.`
  }
  return ''
}

/**
 * Turn a failed create/enable into something a person can act on.
 *
 * Creating and enabling a rule are both owner-gated server-side (_require_admin on
 * POST /disposition/policies and PUT .../enabled). A non-admin gets a 403 whose body says little;
 * left raw it reads like a bug rather than a permission, and the rule silently does not exist.
 */
export function refusalText(err) {
  const raw = String((err && err.message) || err || '').trim()
  if (/\b(403|forbidden|admin|owner|not authori[sz]ed|permission)\b/i.test(raw)) {
    return `Only a platform admin can do that, so the rule was not saved. Ask an admin to add it. (${raw || 'refused by the server'})`
  }
  return raw || 'The server refused the change.'
}

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
  // The five below were already backend-supported (api/disposition.py FIELDS) and already had a
  // plain-English readback (the old EXTRA_PHRASES map, for rules made another way) — but no way
  // to CREATE one here. Same lead/unit wording as before, so moving a field from "readback only"
  // to "buildable" changes nothing about how an existing rule using it reads.
  {
    key: 'pathContains',
    label: 'Path contains',
    field: 'path',
    op: 'contains',
    kind: 'text',
    placeholder: 'e.g. _superseded',
    lead: 'whose path contains ',
  },
  {
    key: 'createdBefore',
    label: 'Created before',
    field: 'created_at',
    op: 'before',
    kind: 'date',
    placeholder: 'YYYY-MM-DD',
    lead: 'created before ',
  },
  {
    key: 'olderThanDays',
    label: 'Older than',
    field: 'age_days',
    op: 'gt',
    kind: 'number',
    unit: 'days',
    placeholder: 'e.g. 1825',
    lead: 'older than ',
  },
  {
    key: 'owner',
    label: 'Owned by',
    field: 'owner',
    op: 'eq',
    kind: 'text',
    placeholder: 'e.g. jane@company.com',
    lead: 'owned by ',
  },
  {
    key: 'ownerInRoster',
    label: 'Owner is in departed-employee roster',
    field: 'owner',
    op: 'in',
    kind: 'list',
    placeholder: 'Paste one email or account name per line',
    lead: 'owned by someone in ',
  },
  {
    key: 'ownerNotInRoster',
    label: 'Owner is not in current-staff roster',
    field: 'owner',
    op: 'not_in',
    kind: 'list',
    placeholder: 'Paste one email or account name per line',
    lead: 'whose owner is outside ',
  },
  {
    key: 'source',
    label: 'Source',
    field: 'source',
    op: 'eq',
    kind: 'text',
    placeholder: 'e.g. drive, sharepoint',
    lead: 'in ',
  },
  // department/business_criticality/regulatory_tags are deliberately NOT here, despite being
  // valid api/disposition.py FIELDS. Nothing anywhere writes them — upsert_document's own
  // docstring says so ("left for an admin/connector to populate later") and a repo-wide grep for
  // a writer of any of the three found none. A condition on a column nothing ever sets would
  // create a rule that silently matches zero files forever, which is exactly the "measured zero"
  // dishonesty this screen's own wording rules exist to prevent. Add them here only once
  // something populates them — file_type/size below are the real version of this same question,
  // answered the other way because both DO have a live writer (doc_class already does; size_kb
  // is wired through in this same change, api/store.upsert_document + both its callers).
  {
    key: 'fileType',
    label: 'File type',
    field: 'doc_class',
    op: 'eq',
    kind: 'text',
    placeholder: 'e.g. pdf-document, spreadsheet, image',
    lead: 'of type ',
  },
  {
    key: 'largerThanKb',
    label: 'Larger than',
    field: 'size_kb',
    op: 'gt',
    kind: 'number',
    unit: 'KB',
    placeholder: 'e.g. 10000',
    lead: 'larger than ',
  },
]

const BY_FIELD_OP = new Map(CONDITIONS.map((c) => [`${c.field}:${c.op}`, c]))

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
  const raw = cond.value
  if (tpl) {
    const value = tpl.kind === 'date' ? formatRuleDate(raw)
      : tpl.kind === 'list'
        ? `${Array.isArray(raw) ? raw.length : 0}-person roster`
      : tpl.unit ? `${raw} ${tpl.unit}`
      : String(raw ?? '')
    return { lead: tpl.lead, value, positional: !!tpl.positional }
  }
  // Last resort — a field/op the builder doesn't (yet) offer, e.g. triage_score, or a legacy
  // combination like department:ne. Still no schema punctuation, but no invented phrasing either.
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
 * The inverse of `draftToMatch`: a stored `match` (array or its JSON-string column form) → the
 * per-condition string values an edit form's draft needs, keyed exactly like `emptyDraft()`'s
 * `values`. Editing a saved rule (build-plan item #2) needs this to pre-fill the same field grid
 * the create form uses, rather than a second, parallel edit UI.
 *
 * A condition whose (field, op) pair the builder does not offer — e.g. `triage_score`, which
 * `ruleSentenceText` already reads back through its own last-resort fallback rather than a
 * template — is silently dropped here too: an edit form can only offer conditions it knows how
 * to build, the same limit the create form already has.
 */
export function matchToDraftValues(match) {
  const values = Object.fromEntries(CONDITIONS.map((c) => [c.key, '']))
  parseMatch(match).forEach((cond) => {
    if (!cond || !cond.field || !cond.op) return
    const tpl = BY_FIELD_OP.get(`${cond.field}:${cond.op}`)
    if (tpl) values[tpl.key] = tpl.kind === 'list'
      ? (Array.isArray(cond.value) ? cond.value.join('\n') : '')
      : String(cond.value ?? '')
  })
  return values
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
    if (c.kind === 'list') {
      const seen = new Set()
      const value = String(raw).split(/[\n,;]+/).map((v) => v.trim()).filter(Boolean)
        .filter((v) => {
          const key = v.toLocaleLowerCase()
          if (seen.has(key)) return false
          seen.add(key)
          return true
        })
      return value.length ? [{ field: c.field, op: c.op, value }] : []
    }
    return [{ field: c.field, op: c.op, value: c.kind === 'number' ? Number(raw) : String(raw) }]
  })
}

/**
 * Why this draft's CONDITIONS cannot be previewed or matched yet, or '' when they can. Unlike
 * `draftProblem` below, this ignores the name field — a name has no bearing on which documents a
 * rule selects, and gating the live preview on it would mean a person filling in conditions
 * first, name last, sees no count until the very last field.
 *
 * The condition-count check is the load-bearing one: a rule with no conditions matches EVERY file
 * in scope, so an accidental empty rule would tag the whole estate for review. It is refused here
 * rather than explained after the fact.
 */
export function matchProblem(draft) {
  const match = draftToMatch(draft)
  if (!match.length) return 'Add at least one condition — a rule with none would match every file in scope.'
  for (const c of CONDITIONS) {
    const raw = (draft && draft.values || {})[c.key]
    if (raw === '' || raw == null) continue
    if (c.kind === 'number' && !(Number(raw) > 0)) return `“${c.label}” must be a number of days greater than zero.`
    if (c.kind === 'date' && !/^\d{4}-\d{2}-\d{2}$/.test(String(raw))) return `“${c.label}” must be a date, as YYYY-MM-DD.`
  }
  return ''
}

/** Why this draft cannot be SUBMITTED yet, or '' when it can. A name plus everything
 *  `matchProblem` requires — see that function for why the two are checked separately. */
export function draftProblem(draft) {
  if (!draft || !String(draft.name || '').trim()) return 'Give the rule a name.'
  return matchProblem(draft)
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

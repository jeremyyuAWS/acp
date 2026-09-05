// R10 — the audit trail for one document: what was changed, by whom or by what, and when.
//
// THE BACKING DATA, and it is real. `GET /scans/{id}/timeline?file=…` → `store.document_timeline`,
// which assembles the trail from rows the pipeline already persists — `scan_runs`, `file_records`,
// `ai_calls`, `hitl_queue`, `hitl_events`, `applied_fixes`, `decision_log` — and infers nothing
// (ADR 0016). Every event is `{ts, kind, title, detail?, actor?, rule_id?}` with `kind` one of
// scan · ai · review · human · fix · publish · decision · certify.
//
// "BY WHOM" IS THE FIELD THE DESIGN WANTS AND THE RECORD BARELY HAS. Of the eight kinds, exactly
// three can carry a person:
//
//   human    — `hitl_events.reviewer`, the reviewer who approved / edited / rejected. A real person,
//              and nullable: a decision recorded without a reviewer name has none to show.
//   decision — `decision_log.actor`. For `hitl.approved` that is the approving user
//              (`accessibility_status.py` passes the caller through). For every action the pipeline
//              records itself — `remediate.applied`, `scan.file_error`, `file.certified` — the actor
//              is the literal string "system".
//   certify  — the same column, and it is always "system".
//
// The other five kinds have NO actor column at all. `scan`, `ai`, `fix` and `publish` come from
// tables that never stored one, and `review` records that ACP queued an item, not that a person did.
//
// So a column headed "who" would be empty on most rows of a real trail, and the temptation is to
// fill it — with the signed-in user, with "ACP", with the owner of the scan. This module refuses.
// It reports the actor when the record HAS one, names the automation from the event kind when it
// does not, and marks which of the two happened (`attribution`), so the screen can distinguish a
// recorded fact from a derived one. Naming the machine that did something is derivable from the
// kind and is true; naming a person is not derivable from anything and is never done.
//
// WHAT THIS TRAIL DOES NOT CONTAIN, stated because the shape of the design implies otherwise:
//   · the value a fix REPLACED. `applied_fixes` stores what was written (surfaced as the event's
//     detail, truncated to 160 chars by the backend) and no prior value. Before → after lives in
//     `remediation_diff`, a different endpoint, and only for fixes that verifiably cleared.
//   · anything scan-wide. The endpoint takes one file; an estate-level trail has no route.
//   · a reversal. Nothing in the schema records a fix being undone.

/** Every event kind `document_timeline` emits, and what it is. */
export const KINDS = ['scan', 'ai', 'review', 'human', 'fix', 'publish', 'decision', 'certify']

// The actor strings the backend writes when there is no person — `log_decision("system", …)` is
// how every pipeline-recorded row is written, so "system" in this column is the ABSENCE of a
// person, not the name of one, and must not be rendered as an identity.
const NOT_A_PERSON = new Set(['system', 'System', 'SYSTEM', 'acp', 'ACP', '-', ''])

// What did it, when the record does not name an actor. Derived from the kind, which the record
// does state — so this is a reading of the trail, not an invention on top of it.
const AGENT = {
  scan: 'ACP scan pipeline',
  ai: 'an AI model',
  review: 'ACP (routing)',
  fix: 'ACP remediation worker',
  publish: 'ACP publish step',
  human: 'a reviewer (not named in the record)',
  decision: 'ACP',
  certify: 'ACP',
}

// Which kinds CHANGED THE DOCUMENT, as opposed to observing or deciding about it. R10's first
// question is "what was changed", and four of the eight kinds are not changes to anything: a scan
// read the file, an AI call produced a candidate value, a routing put it in a queue, a certification
// recorded a verdict. Only the fix and publish steps write bytes.
const CHANGED = new Set(['fix', 'publish'])

// The model an `ai` event used, when the title carries it. `document_timeline` builds that title as
// "AI {surface} · {provider} {model}", so the provider/model tail is a real persisted value rather
// than a guess — but a row missing either produces a shorter title, so this returns null instead of
// slicing whatever happens to be there.
function modelFrom(title) {
  const m = /^AI\s+\S+\s+·\s+(.+)$/.exec(String(title || ''))
  const tail = m && m[1].trim()
  return tail || null
}

/**
 * One timeline event, normalized for rendering.
 *
 * @returns {{ts, kind, title, detail, ruleId, changed, by, attribution}}
 *   by           what to show in the "by" column — a person's identifier, or the named automation.
 *   attribution  'recorded' when `by` came off the row's own actor column; 'derived' when it was
 *                read from the event kind because the record names nobody. The screen prints the
 *                difference, because "the log says Dana approved this" and "this kind of event is
 *                always done by the remediation worker" are different strengths of claim.
 */
export function auditEvent(e) {
  if (!e || !e.ts) return null
  const kind = KINDS.includes(e.kind) ? e.kind : 'decision'
  const actor = typeof e.actor === 'string' ? e.actor.trim() : ''
  const named = actor && !NOT_A_PERSON.has(actor)
  const model = kind === 'ai' ? modelFrom(e.title) : null
  return {
    ts: e.ts,
    kind,
    title: e.title || '',
    detail: e.detail || '',
    ruleId: e.rule_id || e.ruleId || null,
    correlationId: e.correlation_id || e.correlationId || null,
    runId: e.run_id || e.runId || null,
    changed: CHANGED.has(kind),
    by: named ? actor : (model || AGENT[kind] || 'ACP'),
    // An `ai` row's model comes off the persisted title, so naming it is recorded, not derived.
    attribution: named || model ? 'recorded' : 'derived',
  }
}

/**
 * The trail for one document, oldest first.
 *
 * Returns null for anything that is not an array — the caller has not been given a trail, and an
 * empty trail is a claim ("nothing has happened to this document") that an unloaded screen has not
 * earned. `[]` in, `[]` out: that IS the claim, made only once something answered.
 */
export function auditTrail(events) {
  if (!Array.isArray(events)) return null
  return events.map(auditEvent).filter(Boolean)
      .sort((a, b) => String(a.ts).localeCompare(String(b.ts)))
}

/**
 * The one-line summary above the trail: how many events, how many of them changed the document, and
 * how many name a person.
 *
 * `people` is deliberately a count of NAMED actors rather than of human-kind events. A `human` event
 * whose reviewer column is null happened — somebody decided — and the record does not say who; it
 * counts as an event and not as an attribution, which is the honest split.
 */
export function auditSummary(rows) {
  if (!Array.isArray(rows)) return null
  const people = new Set(rows.filter((r) => r.attribution === 'recorded' && r.kind !== 'ai').map((r) => r.by))
  return {
    events: rows.length,
    changes: rows.filter((r) => r.changed).length,
    people: people.size,
    peopleNames: [...people].sort(),
    first: rows.length ? rows[0].ts : null,
    last: rows.length ? rows[rows.length - 1].ts : null,
  }
}

/** ISO → a short absolute stamp. Absolute, never "3 hours ago": an audit trail is read later. */
export function stamp(ts) {
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return String(ts || '')
  return d.toISOString().replace('T', ' ').replace(/\.\d+Z$/, 'Z')
}

// ADR 0021 · Review memory — normalizing the org's house-style rules for the Settings panel.
//
// THE BACKING DATA IS REAL. `GET /org-memory` returns `{rules, enabled}`, where each rule is an
// `org_memory` row: {id, org, kind, rule_id, format, guidance, status, evidence, author,
// created_at, updated_at}. Authored rules (`kind: 'style' | 'glossary'`) are written by an admin
// and are active immediately, because a human wrote them. `kind: 'derived'` rules come only from
// the derivation job, always arrive as `status: 'proposed'`, and carry real counts in `evidence`.
//
// THE ONE THING THIS PANEL MUST NOT DO is imply a rule is shaping drafts when it is not. Two
// separate conditions decide that, and they are independent:
//
//   1. `enabled` — the ACP_REVIEW_MEMORY flag, DEFAULT OFF. With it off, `memory.guidance_for`
//      returns "" and the model prompt is byte-for-byte what it was before ADR 0021. An 'active'
//      rule under a disabled flag is stored, listed, and completely inert. Saying "active" without
//      saying that would be the exact shape of lie this codebase keeps writing tests against.
//   2. `status` — only 'active' rules are ever injected. 'proposed' is awaiting a human decision;
//      'archived' is retired.
//
// So `effective` below is `enabled && status === 'active'`, and the panel renders THAT, not status
// alone.
//
// EVIDENCE IS QUOTED, NEVER SUMMARISED INTO A CLAIM. `api/memory.py:derive_org_memory` emits
// exactly two shapes, each a count over a real window of `hitl_events`. This renders those counts
// and nothing else — no percentage, no confidence, no "strong signal". A shape it does not
// recognise degrades to null and the panel says the evidence could not be read, rather than
// printing a reassuring blank.

/** Statuses the backend accepts on PUT /org-memory/{id}/status. */
export const STATUSES = ['active', 'proposed', 'archived']

/** Kinds an admin may AUTHOR. `derived` is job-only and deliberately absent (the POST route
 *  rejects it with a 422, so offering it in a form would be offering a guaranteed failure). */
export const AUTHORABLE_KINDS = ['style', 'glossary']

const KIND_LABEL = { style: 'House style', glossary: 'Glossary', derived: 'Derived from reviews' }

function parseEvidence(raw) {
  if (raw == null || raw === '') return null
  if (typeof raw === 'object') return raw
  try {
    const v = JSON.parse(raw)
    return v && typeof v === 'object' ? v : null
  } catch {
    return null
  }
}

/**
 * The evidence line for a derived proposal, as a sentence built ONLY from counts the row carries.
 * Returns null when the row has no evidence or a shape this does not recognise — the caller shows
 * "evidence unavailable" rather than an empty confident-looking row.
 */
export function evidenceLine(evidence) {
  const e = parseEvidence(evidence)
  if (!e) return null
  const win = Number.isFinite(e.window_days) ? ` in the last ${e.window_days} days` : ''

  if (Number.isFinite(e.edited) && Number.isFinite(e.median_delta_chars)) {
    const of = Number.isFinite(e.of) ? ` of ${e.of}` : ''
    const d = e.median_delta_chars
    // The sign is the whole point: a negative delta means reviewers SHORTENED the draft.
    const dir = d < 0 ? `${Math.abs(d)} characters shorter` : `${d} characters longer`
    return `Reviewers edited ${e.edited}${of} drafts${win} — median ${dir}.`
  }

  if (Number.isFinite(e.rejected_too_vague)) {
    const of = Number.isFinite(e.of) ? ` of ${e.of}` : ''
    return `Reviewers rejected ${e.rejected_too_vague}${of} drafts as too vague${win}.`
  }

  return null
}

/** One rule, normalized. `effective` is the honest answer to "is this shaping drafts right now?" */
export function normalizeRule(r, { enabled = false } = {}) {
  const status = String(r?.status || '')
  return {
    id: r?.id || null,
    kind: String(r?.kind || ''),
    kindLabel: KIND_LABEL[r?.kind] || r?.kind || 'Rule',
    guidance: r?.guidance || '',
    // null means "every rule / every format" — the backend stores NULL for unscoped rules, and
    // the panel says "all criteria" rather than leaving a blank cell that reads as missing data.
    ruleId: r?.rule_id || null,
    format: r?.format || null,
    status,
    author: r?.author || null,
    createdAt: r?.created_at || null,
    evidence: evidenceLine(r?.evidence),
    // A derived rule with unreadable evidence: distinguish "no evidence recorded" from "we could
    // not parse what was recorded", because only the second is a defect worth anyone chasing.
    evidenceMissing: r?.kind === 'derived' && !!r?.evidence && evidenceLine(r?.evidence) === null,
    effective: enabled && status === 'active',
  }
}

/**
 * The panel's whole model.
 * @param raw the GET /org-memory body, or null when the request failed (which the caller
 *            distinguishes from an empty org — see api.js's getOrgMemory).
 */
export function normalizeOrgMemory(raw) {
  if (!raw || typeof raw !== 'object') {
    return { available: false, enabled: false, proposed: [], active: [], archived: [], counts: {} }
  }
  const enabled = !!raw.enabled
  const rules = (Array.isArray(raw.rules) ? raw.rules : []).map((r) => normalizeRule(r, { enabled }))
  const by = (s) => rules.filter((r) => r.status === s)
  return {
    available: true,
    enabled,
    // Proposals first: they are the only rows that need a decision, which is what the panel is for.
    proposed: by('proposed'),
    active: by('active'),
    archived: by('archived'),
    counts: { proposed: by('proposed').length, active: by('active').length,
              archived: by('archived').length, total: rules.length },
    // How many rules are ACTUALLY shaping drafts. Zero whenever the flag is off, however many are
    // marked active — the number the panel leads with.
    effectiveCount: rules.filter((r) => r.effective).length,
  }
}

// Evidence Card model (PRD v2) — turns a raw HITL queue item into the rich, PR-style
// review card the Intelligent Review Workspace renders. Pure + dependency-light so it
// unit-tests without a React harness; EvidenceCard.jsx renders whatever this returns.
//
// It ASSEMBLES the primitives already shipped this session — nothing here is new data:
//   remediationTrack (auto | assisted | human + the primary action + badge),
//   confidence.js    (High/Med/Low + the `basis` bullet — "evidence over confidence"),
//   hitlMeta         (plain-English "what's wrong"),
//   remediation_diff (real before/after, filtered to this criterion).

import { confidenceForFinding } from './confidence.js'
import { remediationTrack } from './remediationTrack.js'
import { metaFor } from './hitlMeta.js'

const scOf = (ruleId) =>
  String(ruleId || '').replace(/^SC[_ ]?/i, '').replace(/_/g, '.').match(/^\d+\.\d+\.\d+/)?.[0] || ''

// Criteria whose fix IS a value a screen reader will announce (alt text, link text, a title).
// The reviewer approves that text; everything else is a judgement call with nothing to type.
// Single source of truth — ReviewCenter and EvidenceCard must agree on which items get an
// editor, or a reviewer would approve an empty value on one screen and not the other.
export const VALUE_FIX = new Set(['1.1.1', '2.4.4', '2.4.9', '2.4.2', '3.3.2'])

export const isValueFix = (sc) => VALUE_FIX.has(sc)

// A deck fails on slides; a PDF fails on pages. Same idea to a reviewer: "go here".
export const pageNoun = (file) => (String(file || '').split('.').pop().toLowerCase() === 'pptx' ? 'Slide' : 'Page')

// hitl_queue.pages is a comma-separated list of every distinct page this criterion fails on.
// Rendering only the first would tell a reviewer a deck failed on one slide when it failed on
// eleven. Absent pages produce null — we show no location rather than a wrong one.
export function locationLabel(item) {
  const pages = String(item?.pages || '').split(',').map((n) => parseInt(n, 10)).filter(Number.isFinite)
  if (!pages.length) return null
  const noun = pageNoun(item?.file)
  const shown = pages.slice(0, 6)
  const more = pages.length - shown.length
  return `${noun}${pages.length > 1 ? 's' : ''} ${shown.join(', ')}${more > 0 ? ` +${more}` : ''}`
}

// What the review actually was — recorded on hitl_events so the workspace can report REVIEWER
// TIME (the metric that matters) and later calibrate confidence against what humans changed.
//
// `edited` means the approved text differs from what the AI drafted. A reviewer typing a value
// where the AI offered none counts as edited: they authored it. This is not a percentage and
// not an estimate — it is what happened.
export function reviewTelemetry({ editable, status, value, aiDraft, elapsedMs }) {
  const approving = status === 'approved'
  const finalValue = editable && approving ? (value || null) : null
  const edited = !!(editable && approving && (value || '') !== (aiDraft || ''))
  return { finalValue, edited, reviewMs: elapsedMs, aiValue: aiDraft ?? null }
}

// An AI proposal attached to the queue row (hitl_queue.proposals): a concrete, pre-computed
// value the reviewer approves in one click, with the rationale that produced it. A proposal
// is NEVER auto-applied — see api/proposals.py — so the card treats it as a draft to confirm.
// `subjective` marks the values a re-scan can never validate (a decorative call, a sensory
// rewrite, alt-text intent): those are a human judgement, not a machine result.
export const proposalsOf = (item) => (Array.isArray(item?.proposals) ? item.proposals : [])
export const firstProposed = (item) => proposalsOf(item)[0]?.proposed_value ?? null

// The base64 thumbnail of what the reviewer is judging, captured server-side (proposals.thumb_b64).
// Usually the OFFENDING IMAGE — the embedded picture that lacks alt text, or the logo the
// heuristic wants marked decorative. For a reading-order proposal it is the rendered PDF page.
// It is never a generic page-1 render: a PPTX cannot be rasterized at all (api/render.py is
// PDF-only), so for a deck this is the only picture a reviewer can be shown.
export const firstThumb = (item) => proposalsOf(item)[0]?.thumb ?? null

// What the proposal is about, which decides how its thumbnail is sized and described:
// 'decorative' (an image), 'reading-order' (a whole page), or absent (an image).
export const firstKind = (item) => proposalsOf(item)[0]?.kind ?? null

// A page must be shown big enough to read; an embedded image need not be. And the alt text on
// the evidence image has to say what it actually depicts — this is an accessibility product,
// and "Image needing alt text" on a rendered page is exactly the kind of wrong alt we flag.
// These take the kind directly (not the item) because the card components are passed a thumb,
// not the proposal it came from.
export const PAGE_KINDS = new Set(['reading-order'])
export const isPageThumb = (kind) => PAGE_KINDS.has(kind)
export const thumbSize = (kind, imageSize = 84) => (isPageThumb(kind) ? 240 : imageSize)
export const thumbAlt = (kind, file) => (isPageThumb(kind)
  ? `Rendered page of ${file || 'the document'}, for confirming its reading order`
  : `Image needing alt text in ${file || 'the document'}`)

// The rationale + the model that produced the draft, so the reviewer sees WHY, not just WHAT.
export const firstRationale = (item) => proposalsOf(item)[0]?.rationale ?? null
export const firstSource = (item) => proposalsOf(item)[0]?.source ?? null

export function proposalMeta(item) {
  const list = proposalsOf(item)
  if (!list.length) return null
  const subjective = list.some((p) => p && p.kind === 'decorative') || scOf(item?.rule_id) === '1.3.3'
  return { list, validated: !!item?.validated, subjective }
}

// item: a HITL queue row { id, scan_id, file, rule_id, rule_name, finding_count, approved_value,
//                          proposals, validated }
// diffs: this file's remediation_diff rows (getFileRemediationDiffs) — filtered to this SC here.
export function buildEvidenceCard(item, diffs = []) {
  const sc = scOf(item?.rule_id)
  const meta = metaFor(item)
  const fmt = ((item?.file || '').split('.').pop() || 'DOC').toUpperCase()
  const proposal = proposalMeta(item)
  return {
    id: item?.id,
    scanId: item?.scan_id,
    thumbKind: firstKind(item),
    file: item?.file,
    sc,
    fmt,
    wcag: sc ? `WCAG ${sc}` : '—',
    name: item?.rule_name || '',
    severity: meta.sev,
    // Plain-English problem (show, don't tell) — never "Missing Alt Text".
    problem: meta.reason,
    // The AI-drafted value proposed for approval; null → a judgement item with no draft value.
    // A server-side proposal (hitl_queue.proposals) wins over a previously-approved value:
    // it is the current recommendation, pre-computed at remediation time so the reviewer
    // confirms a concrete value instead of drafting one from a blank.
    recommendation: firstProposed(item) ?? item?.approved_value ?? null,
    // The proposals themselves + their rationale, so the card can show WHY, not just what.
    proposal,
    // { track: auto|assisted|human, action: 'Approve & Apply'|…, badge } — the primary CTA.
    track: remediationTrack({ sc }),
    // { level: {key,label,rank}, basis } — the WHY, never a fabricated %. A proposal awaiting
    // approval is never High: nothing an AI proposed is trusted until a human accepts it.
    confidence: confidenceForFinding({ sc, proposal }),
    // Real before→after for THIS criterion (nothing illustrative).
    diffs: (diffs || []).filter((d) => scOf(d.rule_id) === sc),
    // Does approving this item actually resolve the criterion?
    //
    // JUDGEMENT finding (a contrast ratio accepted, a link text deemed adequate): yes. The
    // sign-off IS the resolution — a re-scan can never clear it — so the backend
    // (store.mark_file_compliant_if_reviewed) certifies the file on approval.
    //
    // VALUE-FIX finding (alt text, a title, a label): NO. Approving stores approved_value as
    // compliance evidence and stops there; no remediator consumes it and no job is enqueued
    // (api/routes/hitl.py). The document is never modified, so the criterion still fails.
    // This was a hardcoded `{ before: 'Fail', after: 'Pass' }`, which promised a Pass the
    // backend now refuses to grant — and which certified a PPTX 100/100 while its ten images
    // were still undescribed.
    certifiesOnApprove: !isValueFix(sc),
    impact: { before: 'Fail', after: isValueFix(sc) ? 'Fail' : 'Pass' },
    findingCount: item?.finding_count || 1,
    // Where in the document to look — null when the analyser attributed nothing.
    location: locationLabel(item),
    page: item?.page ?? null,
    // The actual image the reviewer must judge, and the evidence behind the draft.
    thumb: firstThumb(item),
    rationale: firstRationale(item),
    proposalSource: firstSource(item),
  }
}

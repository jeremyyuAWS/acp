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
import { WCAG } from './wcagCatalog.js'

const _WCAG_BY_SC = Object.fromEntries(WCAG.map((c) => [c.sc, c]))
// Who is blocked when a criterion under each WCAG principle fails — a plain-English impact clause,
// composed from the maintained catalog, never invented per finding.
const _PRINCIPLE_IMPACT = {
  Perceivable: 'people using a screen reader or other assistive technology cannot access this content',
  Operable: 'people navigating by keyboard or assistive technology cannot operate it',
  Understandable: 'the content is harder to understand, and assistive technology may mishandle it',
  Robust: 'assistive technology may fail to interpret it correctly',
}
import { metaFor } from './hitlMeta.js'

const scOf = (ruleId) =>
  String(ruleId || '').replace(/^SC[_ ]?/i, '').replace(/_/g, '.').match(/^\d+\.\d+\.\d+/)?.[0] || ''

// Criteria whose fix is CONTENT the document must carry — alt text, link text, a title, a
// `lang` marking. Approving one is not the resolution: the value still has to be written in
// and the file re-scanned. Everything else (a contrast ratio accepted, a link deemed adequate
// as it stands) is a judgement call whose resolution IS the human sign-off.
//
// Single source of truth. It decides three things at once, so a criterion missing from it goes
// wrong three ways: no editor appears, the card promises "Fail → Pass after approval", and
// "Approve all judgement items" sweeps it up in bulk. 3.1.2 was missing, so a Language-of-Parts
// finding certified its file while the passage was still unmarked.
export const VALUE_FIX = new Set([
  '1.1.1',   // alt text
  '2.4.4', '2.4.9',   // link text
  '2.4.2',   // document / page title
  '3.3.2',   // form-field label
  '3.1.1',   // document language — a `lang` attribute, written not merely agreed to
  '3.1.2',   // language of parts — a `lang` marking on each foreign passage
  '1.3.3',   // sensory characteristics — the sentence itself is rewritten
])

export const isValueFix = (sc) => VALUE_FIX.has(sc)

// What a proposal's raw value means once written. 3.1.2 proposes a bare ISO code ("es"), which
// tells a reviewer nothing on its own; show the markup it becomes.
const LANG_NAMES = { en: 'English', es: 'Spanish', fr: 'French', de: 'German', pt: 'Portuguese',
                     it: 'Italian', nl: 'Dutch', zh: 'Chinese', ja: 'Japanese', ko: 'Korean',
                     ar: 'Arabic', hi: 'Hindi', ru: 'Russian', pl: 'Polish', tr: 'Turkish' }

export function formatProposedValue(sc, value) {
  const v = String(value ?? '')
  if ((sc === '3.1.2' || sc === '3.1.1') && /^[a-z]{2}(-[A-Za-z]{2,4})?$/.test(v)) {
    const name = LANG_NAMES[v.slice(0, 2).toLowerCase()]
    return `lang="${v}"${name ? ` — ${name}` : ''}`
  }
  return v
}

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
//
// Fall back to the first evidence thumb when there's no proposal: a 1.1.1 row where the vision
// model returned nothing lands its image bytes in `evidence[]` (thumb captured, no drafted value)
// rather than `proposals[]`. Without this fallback such a card showed NO picture at all — the
// server thumbnail route is PDF-only, so a deck image was invisible. The reviewer must always see
// the image they're being asked to describe, whether or not the AI managed a draft.
export const firstThumb = (item) => proposalsOf(item)[0]?.thumb ?? evidenceOf(item)[0]?.thumb ?? null

// The `part#rId` locator of the first offending shape — what the geometry endpoint resolves to a
// bounding box for the page-preview overlay (ADR 0018). Same source-of-truth precedence as the
// thumb: a drafted proposal's locator, else the first deferred evidence image's. null when the
// finding carries no shape locator (a judgement item, a page-level PDF finding) → no box drawn.
export const firstLocator = (item) => proposalsOf(item)[0]?.locator ?? evidenceOf(item)[0]?.locator ?? null

// The KIND of image, read from the vision model's OWN description words (#130) — not a separate,
// fuzzy classifier. A chart wants a data-trend description; an icon wants two words; a photo wants
// the scene: naming the kind tells the reviewer what a good alt text looks like here. Honest and
// zero-cost: it's the model's own noun, surfaced as a routing hint, or null when nothing matches
// (never guessed). Ordered specific→generic so "bar chart" wins over the bare "image".
const _IMAGE_KINDS = [
  [/\b(bar|line|pie|column|scatter|area)?\s*(chart|graph|plot|histogram)\b/, '📊', 'Chart', 'describe the trend and the key figure, not just "a chart"'],
  [/\b(flow ?chart|diagram|workflow|schematic|org chart)\b/, '🔀', 'Diagram', 'describe what it shows and the flow between parts'],
  [/\bscreenshot\b/, '🖥️', 'Screenshot', 'describe the screen and the key text on it'],
  [/\b(table|spreadsheet|grid of)\b/, '🗂️', 'Table', 'summarise what the table conveys'],
  [/\b(map|floor ?plan)\b/, '🗺️', 'Map', 'describe the location or layout shown'],
  [/\blogo\b/, '🔖', 'Logo', 'usually just the organisation name'],
  [/\b(icon|glyph|symbol|button)\b/, '🔣', 'Icon', 'name the action or meaning in a word or two'],
  [/\b(photo|photograph|portrait|headshot)\b/, '📷', 'Photo', 'describe the scene and who or what is in it'],
  [/\b(illustration|drawing|cartoon|graphic)\b/, '🖼️', 'Illustration', 'describe the subject and its meaning'],
]
export function describedImageType(item) {
  const text = String(firstProposed(item) ?? firstRationale(item) ?? '').toLowerCase()
  if (!text) return null
  for (const [re, icon, label, hint] of _IMAGE_KINDS) {
    if (re.test(text)) return { icon, label, hint }
  }
  return null
}

// The images this row asks a human to describe (hitl_queue.evidence): [{locator, thumb}, …],
// one per deferred image, captured at remediation time whether or not the vision model ran.
// NOT proposals — there is no value to approve — so they never reach proposalMeta or
// confidence.js. A 1.1.1 row routinely carries nineteen of these, which is why the card shows
// a STRIP: a single thumbnail beside "19 findings" would tell the reviewer they are describing
// that one image.
export const evidenceOf = (item) => (Array.isArray(item?.evidence) ? item.evidence : [])

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

// Should the card's HERO be the isolated embedded image (its own r:embed bytes), rather than a
// whole-page render? For xlsx it must: an Office page render of a spreadsheet is the ENTIRE sheet —
// a grid of cells with the flagged picture as a tiny region — so the reviewer can't tell which image
// is under review or see it clearly (ADR 0018's bounding-box crop self-hides for Office). The
// per-image thumb IS the offending picture, already resolved server-side (remediate_office
// ._image_bytes_for), so it is the honest hero. Scoped to xlsx image findings — a real embedded
// image, never a page-kind reading-order thumb. pptx/docx keep today's behaviour: their page render
// is either useful or self-hides. Pure on the card; the caller still checks the thumb is present.
export const leadWithIsolatedImage = (card) =>
  (card || {}).fmt === 'XLSX' && !isPageThumb((card || {}).thumbKind)
export const thumbAlt = (kind, file) => (isPageThumb(kind)
  ? `Rendered page of ${file || 'the document'}, for confirming its reading order`
  : `Image needing alt text in ${file || 'the document'}`)

// An applied-fix receipt ("Recent AI fixes") carries no `kind` — the applied_fixes table has no
// such column — so the FORMAT decides. A PDF figure's alt text is written from a render of its
// PAGE (remediate_pdf._fix_pdf_figure_alt); an Office image's is written from the embedded image
// itself. Calling a page render "the image" would be inaccurate alt text, in the product whose
// job is to find inaccurate alt text.
export const appliedFixAlt = (file) => (
  String(file || '').split('.').pop().toLowerCase() === 'pdf'
    ? `Rendered page of ${file}, from which the AI wrote alt text`
    : `Image in ${file || 'the document'} that the AI wrote alt text for`)

// The OFFENDING value the proposal is about to replace: the foreign-language passage, the
// vague link text, the sensory phrase. It is the concrete "what was there" half of the
// before → after a reviewer is approving. `dbItemToUi` used to synthesise a `before` from the
// finding's generic detail text, which said the same thing for every instance of a criterion.
export const firstBefore = (item) => proposalsOf(item)[0]?.before ?? null

// The page the finding sits on (hitl_queue.page — the lowest page the analysers attributed),
// so the card can show THAT page rather than the document's cover. Null when the analysers
// never attributed one: we show no page rather than a wrong one, and never default to 1.
export const pageOf = (item) => {
  const p = item?.page
  return Number.isInteger(p) && p > 0 ? p : null
}

// The rationale + the model that produced the draft, so the reviewer sees WHY, not just WHAT.
export const firstRationale = (item) => proposalsOf(item)[0]?.rationale ?? null
export const firstSource = (item) => proposalsOf(item)[0]?.source ?? null

// comparisonFor / noDraftHint / NO_DRAFT_HINT used to live here. They served Remediate's
// WhyReview + ReviewItemCard, deleted in #108 as unreachable, and had no other caller. The live
// card builds its own before/after from remediation_diff (EvidenceCard + BeforeAfterEvidence) and
// states a missing draft through draftMsg, so nothing here was feeding it.

export function proposalMeta(item) {
  const list = proposalsOf(item)
  if (!list.length) return null
  const subjective = list.some((p) => p && p.kind === 'decorative') || scOf(item?.rule_id) === '1.3.3'
  return { list, validated: !!item?.validated, subjective }
}

// Split a stored file reference for display. hitl_queue.file is sometimes a bare name and
// sometimes a path; both must render, and neither may invent the other half.
//
// Exported because reviewGrouping.docIdentity needs exactly this split for the inbox cards and
// the by-document headings. Two implementations of "which part of this is the folder" is how
// one screen shows a document at a path and another shows it at the root.
export const baseOf = (p) => String(p || '').split('/').filter(Boolean).pop() || ''
export const dirOf = (p) => {
  const parts = String(p || '').split('/').filter(Boolean)
  return parts.length > 1 ? parts.slice(0, -1).join('/') : ''
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
    // The images awaiting a description. Separate from `thumb`/`proposal` on purpose.
    evidence: evidenceOf(item),
    page: pageOf(item),
    file: item?.file,
    // The document this card is asking about, split for display. The card showed format,
    // criterion and severity but never the filename — its accessible name was literally
    // "Review —", so a screen-reader user was told nothing about what they were approving.
    //
    // Name AND folder, because the name alone does not identify the document: this estate
    // holds Clinical-FAQ-39.html and Clinical-FAQ-54.html, and elsewhere the same basename
    // appears under different folders. `dir` is '' when the row carries a bare filename, and
    // the card then shows nothing rather than a fabricated path.
    fileName: baseOf(item?.file),
    fileDir: dirOf(item?.file),
    sc,
    fmt,
    wcag: sc ? `WCAG ${sc}` : '—',
    name: item?.rule_name || '',
    severity: meta.sev,
    // Plain-English problem (show, don't tell) — never "Missing Alt Text".
    problem: meta.reason,
    // The raw finding detail (e.g. a contrast finding's "#hex on #hex is X.X:1 (needs Y:1)") — the
    // card parses it for structured visual evidence like the contrast swatch. Prose-only otherwise.
    detail: item?.detail || '',
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
    // VALUE-FIX finding (alt text, a title, a label): NOT on the approval itself. Approving
    // schedules the write (api/routes/hitl.py → apply_approved_values), which applies each
    // value at its locator, re-scans the written copy, and certifies only if the criterion
    // actually cleared. So the card must not promise a Pass here: at the moment the reviewer
    // clicks, the document still fails. This was a hardcoded `{ before: 'Fail', after: 'Pass' }`,
    // which certified a PPTX 100/100 while its ten images were still undescribed.
    certifiesOnApprove: !isValueFix(sc),
    impact: { before: 'Fail', after: isValueFix(sc) ? 'Fail' : 'Pass' },
    findingCount: item?.finding_count || 1,
    // Where in the document to look — null when the analyser attributed nothing.
    location: locationLabel(item),
    // The actual image the reviewer must judge, and the evidence behind the draft.
    thumb: firstThumb(item),
    // The offending shape's locator — feeds the page-preview bounding-box overlay (ADR 0018).
    locator: firstLocator(item),
    rationale: firstRationale(item),
    proposalSource: firstSource(item),
  }
}

// The verification ladder — the honest, connected pipeline for ONE finding, each stage derived from
// a real signal so the reviewer sees exactly where in the flow they are. It never claims a stage
// that hasn't happened: for a value-fix the write + re-scan run ON approval, so those stages read
// 'todo' until the proposal was already applied and re-scan-validated (`proposal.validated`) — the
// card must never show a green "written / re-scanned" while the document still fails.
// Returns [{ label, state: 'done' | 'current' | 'todo' }] in pipeline order.
export function verificationLadder(card) {
  const c = card || {}
  const hasProposal = !!(c.proposal && c.proposal.list && c.proposal.list.length)
  const validated = !!(c.proposal && c.proposal.validated)
  // Judgement finding (contrast accepted, link text deemed adequate): nothing is written and nothing
  // is re-scanned — the human sign-off IS the resolution, so the pipeline is short and honest.
  if (c.certifiesOnApprove) {
    return [
      { label: 'Detected', state: 'done' },
      { label: 'Human review', state: 'current' },
      { label: 'Certified', state: 'todo' },
    ]
  }
  // Value-fix pipeline: generate → human review → write → re-scan → certify. When the proposal was
  // already applied + re-scan-validated in a prior batch, the write and re-scan are behind us and the
  // human is the last gate before certification; otherwise both happen when the reviewer approves.
  if (validated) {
    return [
      { label: 'AI draft generated', state: 'done' },
      { label: 'Written to document', state: 'done' },
      { label: 'Re-scan verified', state: 'done' },
      { label: 'Human review', state: 'current' },
      { label: 'Certified', state: 'todo' },
    ]
  }
  return [
    { label: hasProposal ? 'AI draft generated' : 'Detected', state: 'done' },
    { label: 'Human review', state: 'current' },
    { label: 'Written to document', state: 'todo' },
    { label: 'Re-scan verified', state: 'todo' },
    { label: 'Certified', state: 'todo' },
  ]
}

// The concrete, independently-checkable signals behind a finding — the EVIDENCE, never a fabricated
// score (ADR 0016 forbids a %). Every item is a real field the pipeline produced, tagged with a
// GROUP so the card can cluster them (Detection / Reasoning / Document state) the way a reviewer
// scans them. The subjective-wording caveat is intentionally NOT here — it's the dedicated
// `whyHumanReview` panel. Empty list is correct when the finding carried no evidence — show nothing
// rather than fake it. Returns [{ tone: 'ok' | 'warn', text, group }].
export function evidenceSignals(card) {
  const c = card || {}
  const out = []
  const seen = new Set()
  const add = (group, tone, text) => {
    const t = (text || '').trim()
    if (t && !seen.has(t)) { seen.add(t); out.push({ tone, text: t, group }) }
  }
  // how it was detected — deterministic rule vs AI/heuristic — straight from the confidence basis
  if (c.confidence && c.confidence.basis) add('Detection', 'ok', c.confidence.basis)
  // the model's reasoning for THIS draft (OCR-anchored evidence etc.), when present
  add('Reasoning', 'ok', c.rationale || (c.proposal && c.proposal.list && c.proposal.list[0] && c.proposal.list[0].rationale))
  // the prior state we're replacing — a genuinely empty "before" is real evidence the value was missing
  const before = (c.diffs && c.diffs[0] && c.diffs[0].before)
    || (c.proposal && c.proposal.list && c.proposal.list[0] && c.proposal.list[0].before)
  if (before && /\b(no|empty|none|missing)\b/i.test(String(before))) add('Document state', 'ok', 'No existing value on the element')
  return out
}

// Verifiable trust states (ADR 0019 §3a) — the evidence-based REPLACEMENT for a confidence label.
// Every state is derived from a real field; none is a number or an opaque level.
//   grounding  — what the value is anchored in (OCR / document text / a pure visual guess)
//   validation — whether an objective check has actually passed
// The third axis, "review requirement", is the `whyHumanReview` callout — kept separate because it
// carries a full explanation, not just a label. Returns { grounding: {state,label,tone}|null,
// validation: {state,label,tone} }.
// The three verifiable trust-state axes (ADR 0019 §3a) that REPLACE a confidence label in the AI
// context — each an evidence-based enum, none a fabricated number. Every state is derived from a
// real signal the card already carries: the grounded flag / rationale text (Grounding), the
// re-scan + applied flags (Validation), and the track + subjectivity + grounding (Review
// requirement). `code` is the ADR §3a vocabulary (for the audit + envelope); `state` is kept for
// backward-compat with explainFinding; `label`/`tone` drive the chips.
export function trustStates(card) {
  const c = card || {}
  const p0 = c.proposal && c.proposal.list && c.proposal.list[0]
  const rat = String(c.rationale || (p0 && p0.rationale) || '').toLowerCase()
  const explicit = p0 && typeof p0.grounded === 'boolean' ? p0.grounded : null
  let grounding = null
  if (explicit === true || /\b(ocr|anchored|read from the image|chart label|text read)\b/.test(rat)) {
    const chart = /chart label|axis|legend/.test(rat)
    grounding = { state: 'grounded', code: chart ? 'grounded_in_chart_labels' : 'grounded_in_ocr',
                  label: chart ? 'Grounded in the chart’s own labels' : 'Grounded in text read from the source', tone: 'ok' }
  } else if (explicit === false || /vision description only|no text in the image|visual (guess|interpretation)/.test(rat)) {
    grounding = { state: 'visual_only', code: 'visual_interpretation_required',
                  label: 'Visual interpretation — no text anchor', tone: 'warn' }
  } else if (c.sc && c.sc !== '1.1.1' && (p0 || c.recommendation)) {
    grounding = { state: 'document_text', code: 'grounded_in_document_text', label: 'Grounded in document text', tone: 'ok' }
  } else if (c.sc === '1.1.1' && (p0 || c.recommendation)) {
    grounding = { state: 'visual_only', code: 'no_reliable_anchor', label: 'No reliable text anchor — confirm the wording', tone: 'warn' }
  }
  let validation
  if (c.proposal && c.proposal.validated) validation = { state: 're_scan_passed', code: 're_scan_passed', label: 'Re-scan passed', tone: 'ok' }
  else if (c.certifiesOnApprove) validation = { state: 'deterministic_passed', code: 'deterministic_checks_passed', label: 'Deterministic check — your sign-off certifies', tone: 'ok' }
  else validation = { state: 'not_yet_written', code: 'not_yet_written', label: 'Not yet written to document', tone: 'todo' }
  return { grounding, validation, review: reviewRequirement(c, grounding, validation) }
}

// The Review-requirement axis (ADR 0019 §3a) — WHY this needs (or doesn't need) a human, as a
// checkable enum, not a score. Derived from whether a draft exists, how anchored it is, and whether
// validation has already cleared it.
export function reviewRequirement(card, grounding, validation) {
  const c = card || {}
  const hasDraft = !!(c.recommendation || (c.proposal && c.proposal.list && c.proposal.list.length))
  if (!hasDraft) {
    return { code: 'manual_remediation', label: 'Needs a human to author the fix', tone: 'warn' }
  }
  if (validation && validation.code === 're_scan_passed') {
    return { code: 'safe_to_auto_apply', label: 'Evidence complete — safe to approve', tone: 'ok' }
  }
  if (grounding && (grounding.tone === 'warn')) {
    return { code: 'human_wording_review', label: 'Human wording review — the description is a visual interpretation', tone: 'warn' }
  }
  if (c.certifiesOnApprove) {
    return { code: 'human_wording_review', label: 'Human judgement — your sign-off resolves it', tone: 'todo' }
  }
  return { code: 'human_wording_review', label: 'Confirm the drafted wording before it is written', tone: 'todo' }
}

// "✨ Explain this finding" — a deterministic, keyless plain-English explanation of ONE finding.
// Composed entirely from real catalog + finding fields (the WCAG requirement, its principle → who
// is blocked, the drafted value, the grounding + validation states, the human-review reason). No
// model call, so it works with no key and offline; no fabricated number. This is the radiologist-
// style "what / why / what changes / what next" primer a reviewer reads before deciding.
export function explainFinding(card, { trust = null, whyReview = null } = {}) {
  const c = card || {}
  const cat = _WCAG_BY_SC[c.sc] || {}
  const parts = []
  // 1. what the criterion requires + who is blocked while it fails
  const req = String(cat.req || c.problem || '').replace(/\s*\.\s*$/, '')
  const impact = _PRINCIPLE_IMPACT[cat.principle] || 'some users cannot access this content'
  if (req) parts.push(`WCAG ${c.sc}${cat.name ? ` (${cat.name})` : ''} requires: ${req}. It currently fails, so ${impact}.`)
  // 2. what ACP did + how well anchored the draft is
  const rec = c.recommendation
  if (rec) {
    const g = trust && trust.grounding
    const anchor = g && g.state === 'grounded' ? ' It is anchored in text read from the source.'
      : g && g.state === 'visual_only' ? ' It is a visual interpretation, so the wording may need a human eye.'
      : ''
    parts.push(`ACP drafted a correction — “${String(rec).slice(0, 160)}”.${anchor}`)
  } else {
    parts.push('ACP could not draft this automatically, so it needs your input.')
  }
  // 3. why a human is here + what approving actually does
  if (whyReview) parts.push(whyReview)
  const v = trust && trust.validation
  if (v && v.state === 're_scan_passed') parts.push('A re-scan already confirmed the fix, so approving certifies it.')
  else if (v && v.state === 'not_yet_written') parts.push('It has not been written to the document yet — approving writes it and re-scans to confirm.')
  else if (v && v.state === 'deterministic_passed') parts.push('This is a deterministic finding, so your sign-off resolves it.')
  return parts.join(' ')
}

// "Why this recommendation?" — the STRUCTURED reasoning chain a reviewer can read in one glance
// (HITL vision #9): the problem, what ACP actually detected (grounding evidence + image kind), the
// suggested value, and the WCAG requirement that makes it necessary. Every line is a real finding/
// catalog field — no model call, no fabricated number. `ocrText` is the actual text read from the
// image when present; `kind` is the model's own noun for the object. Any absent line is omitted,
// never invented. Returns { problem, detected: [{label, value}], suggested, because } or null.
export function whyRecommendation(card, { trust = null, kind = null, ocrText = null } = {}) {
  const c = card || {}
  const cat = _WCAG_BY_SC[c.sc] || {}
  if (!c.problem && !cat.req && !c.recommendation) return null
  const detected = []
  // What was read from the source (grounding). Prefer the real OCR string; else name the anchor.
  const g = trust && trust.grounding
  const ocr = (ocrText || '').trim()
  if (ocr) detected.push({ label: 'Text read from the image (OCR)', value: `“${ocr.slice(0, 90)}”` })
  else if (g && g.state === 'grounded') detected.push({ label: 'Grounding', value: 'anchored in text read from the source' })
  else if (g && g.state === 'document_text') detected.push({ label: 'Grounding', value: 'anchored in the surrounding document text' })
  else if (g && g.state === 'visual_only') detected.push({ label: 'Grounding', value: 'a visual interpretation (no text to anchor it — confirm the wording)' })
  // What the model saw it as (image kind), when recognised.
  if (kind && kind.label) detected.push({ label: 'Detected', value: kind.label })
  const impact = _PRINCIPLE_IMPACT[cat.principle] || 'some users cannot access this content'
  const req = String(cat.req || '').replace(/\s*\.\s*$/, '')
  return {
    problem: c.problem || null,
    detected,
    suggested: c.recommendation ? String(c.recommendation).slice(0, 200) : null,
    because: req ? `WCAG ${c.sc}${cat.name ? ` (${cat.name})` : ''} requires ${req.charAt(0).toLowerCase() + req.slice(1)} — otherwise ${impact}.` : null,
  }
}

// Deterministic-validation receipt (vision #12/#33) — the concrete proof that a fix was actually
// APPLIED and machine-verified, kept SEPARATE from the AI generation ("never simply Done"). Every
// tick is a real fact: a remediation_diff row is written ONLY for a criterion whose fix cleared the
// residual re-scan, so its presence proves write + re-open + re-scan + clear; a validated proposal
// proves the same. Returns an ordered [{ label, done:true }] when there IS applied+verified evidence,
// else null — a pending value-fix has nothing to certify yet (the ladder shows its pending path).
export function validationChecklist(card) {
  const c = card || {}
  const applied = (c.diffs && c.diffs.length > 0) || !!(c.proposal && c.proposal.validated)
  if (!applied) return null
  return [
    { label: 'Value written into the document', done: true },
    { label: 'Document re-opened and re-scanned', done: true },
    { label: `${c.sc || 'Criterion'} cleared on the re-scan`, done: true },
  ]
}

// The irreducibly-human criteria (the document-core 20 "HITL-six" and their kin): findings a model must
// NOT settle alone, each with the TRUE, criterion-specific reason a person is required. Keyed by
// WCAG SC so the "Why human review?" callout states why THIS check can't be a machine call —
// an authorial, editorial, or brand/legal judgement — instead of a generic "no signal covers it".
// Every line names a real limitation; none implies ACP could do it and chose not to.
const HUMAN_REVIEW_BY_SC = {
  '1.2.1': 'A transcript for audio must be written by a person — its accuracy is a compliance liability ACP will not synthesize.',
  '1.2.2': 'Captions must be authored and time-synced by a person — ACP flags the gap but will not fabricate caption text.',
  '1.2.3': 'An audio description or media alternative is human-authored content — ACP marks it required, it does not invent it.',
  '1.3.2': 'The correct reading order of a complex layout depends on what the author meant to convey — auto-linearising it can silently reorder meaning, so a person confirms it.',
  '1.3.3': 'Whether an instruction relies only on shape, colour, or position — and how to reword it without losing meaning — is an editorial judgement.',
  '1.4.5': 'Whether text-in-image is essential (a logo or brand mark, and so exempt) or a fixable design choice is a brand/legal call — the “essential” option records it.',
  '1.4.9': 'Whether text-in-image is essential (a logo or brand mark, and so exempt) is a brand/legal call — the “essential” option records it.',
  '2.4.6': 'Whether a heading truly describes its section is a judgement about the author’s intent, not a pattern a model can settle.',
  '2.4.10': 'Whether the document’s section structure is logically correct depends on what the author meant to convey.',
}

// "Why am I reviewing this?" — the honest reason a human is in the loop for this finding, derived
// from real signals so the reviewer understands the ask before approving. A criterion-specific
// reason (the HITL-six) wins over the generic confidence-derived one, because it says something
// TRUE about that check rather than a hedge. Null for a straightforward deterministic confirmation
// with nothing to explain.
export function whyHumanReview(card) {
  const c = card || {}
  const bySc = HUMAN_REVIEW_BY_SC[c.sc]
  if (bySc) return bySc
  if (c.proposal && c.proposal.subjective)
    return 'The wording is a judgement call — several valid descriptions exist, so a person confirms it before it is certified.'
  const level = c.confidence && c.confidence.level && c.confidence.level.key
  if (level === 'low') return 'No automated signal fully covers this criterion — it needs your judgement.'
  if (level === 'medium') return 'Detected by AI / heuristic rather than a deterministic rule, so a human confirms the call before certification.'
  return null
}

// "Why this is safe to approve" — the AFFIRMATIVE counterpart to whyHumanReview. A reviewer should
// build confidence from what has ALREADY been checked, not from digging through the audit trail.
// This composes ONLY the positive facts that are genuinely true for THIS card — each derived from a
// real trust signal (grounding, validation, deterministic sign-off, no-prior-value), never a
// fabricated reassurance. It is deliberately silent when the honest answer is "this still needs
// judgement" (visual-only wording, manual authoring): there we return null and let whyHumanReview
// carry the ask rather than paint a false green. Returns { points: [string] } or null.
export function whySafeToApprove(card, { trust = null } = {}) {
  const c = card || {}
  const t = trust || trustStates(c)
  const g = t.grounding
  const v = t.validation
  // Honest gate 1: the irreducibly-human criteria (the HITL-six + kin) are never "safe to approve"
  // on autopilot — captions, reading order, a brand/essential call are judgements a person must
  // make, even though their sign-off certifies. Leading with a green box would contradict the
  // "Why human review?" reason those same criteria carry. (certifiesOnApprove alone can't tell a
  // deterministic contrast check apart from a caption sign-off — this list can.)
  if (HUMAN_REVIEW_BY_SC[c.sc]) return null
  // Honest gate 2: a visual-only draft (no text anchor) is precisely the wording a human must vet —
  // never paint it green. A pure manual-authoring finding needs no gate: it produces no positive
  // point below, so it returns null on its own.
  if (g && g.tone === 'warn') return null
  const points = []
  if (v && v.state === 're_scan_passed') points.push('A re-scan already confirmed the fix clears this check.')
  else if (c.certifiesOnApprove || (v && v.state === 'deterministic_passed')) points.push('This is a deterministic check — your sign-off is the certification; nothing is guessed.')
  if (g && g.state === 'grounded') points.push('The wording is anchored in text read directly from the source, not a guess.')
  else if (g && g.state === 'document_text') points.push('The value is drawn from the document’s own text.')
  // an empty "before" means approving only fills a gap — it cannot overwrite good content
  if ((evidenceSignals(c) || []).some((s) => /no existing value/i.test(s.text)))
    points.push('There was no existing value on the element — approving only adds what was missing, it overwrites nothing.')
  return points.length ? { points } : null
}

// ── Document page heatmap (vision §17) ─────────────────────────────────────────
// Group instance indexes by their MEASURED page ({idx: page} → [[page, [idxs…]], …],
// sorted by page). Pure: EvidenceCard feeds it the geometry results and renders one
// clickable chip per page; clicking jumps the hero to that page's first finding.
export function groupPages(pageMap) {
  const byPage = new Map()
  for (const [i, p] of Object.entries(pageMap || {})) {
    if (!Number.isFinite(Number(p))) continue
    const page = Number(p)
    if (!byPage.has(page)) byPage.set(page, [])
    byPage.get(page).push(Number(i))
  }
  return [...byPage.entries()]
    .map(([page, idxs]) => [page, idxs.sort((a, b) => a - b)])
    .sort((a, b) => a[0] - b[0])
}

// ── Three review types (canonical HITL vision: don't force three different jobs into one
// generic card). Classified per ITEM from data that already exists — never per SC, because a
// 1.1.1 row can arrive with AI drafts (validate them) or with only evidence thumbnails
// (author a description). The type tells the reviewer WHAT KIND OF WORK this is before they
// open it, and gives each kind its own promise + primary verb.
//
//   proposal — AI/heuristic drafted a concrete value; the human validates and approves it.
//   confirm  — ACP already applied a deterministic fix ('auto/verify' pseudo-rule); the human
//              eyeballs and confirms — no authoring, no wording judgement.
//   author   — ACP detected the issue but has no safe draft; the human writes the fix and
//              ACP applies + re-validates it.
export function reviewType(item) {
  if (String(item?.rule_id || '').startsWith('auto/')) return 'confirm'
  const props = proposalsOf(item)
  if (props.some((p) => String(p?.proposed_value ?? '').trim() !== '')) return 'proposal'
  return 'author'
}

export const REVIEW_TYPES = {
  proposal: {
    key: 'proposal', icon: '✨', label: 'AI proposals — validate & approve',
    promise: 'ACP drafted each fix. Check it against the evidence and approve — or edit it first.',
  },
  confirm: {
    key: 'confirm', icon: '🛡', label: 'Deterministic fixes — confirm',
    promise: 'ACP already applied these rule-based fixes and re-validated them. Eyeball and confirm.',
  },
  author: {
    key: 'author', icon: '✍️', label: 'Needs your judgement — author the fix',
    promise: 'No safe automatic fix exists for these. You write the value; ACP applies and re-scans it.',
  },
}

// ── Review Intent (AI Work Inbox reframe) ───────────────────────────────────────
// ONE plain-language sentence, rendered at the TOP of the card, that answers "why am I here and
// what do I do?" before any audit detail. Task-first, no jargon ("AI/heuristic detection",
// "semantic judgement", "review suggested" all move under Details). Keyed off reviewType and
// flavoured by the finding's own noun.
const _SC_NOUN = {
  '1.1.1': 'image', '2.4.4': 'link', '2.4.9': 'link', '2.4.6': 'heading', '2.4.10': 'heading',
  '3.1.2': 'passage', '1.3.3': 'instruction', '4.1.2': 'form field', '2.4.2': 'document',
}
export function reviewIntent(item, sc = null) {
  const t = reviewType(item)
  const noun = _SC_NOUN[String(sc || '')] || 'item'
  if (t === 'confirm') return 'ACP applied and verified this fix — confirm it before certification.'
  if (t === 'proposal')
    return `ACP drafted a fix for this ${noun}. Check the wording against the evidence and approve — or edit it first.`
  return `ACP flagged this ${noun} but couldn’t generate a trustworthy fix, so it needs you to write one.`
}

// The single primary button's label, by workflow — so the one action reads plainly ("Approve AI
// fix" / "Confirm fix" / "Approve description") instead of exposing internal apply semantics.
export function primaryActionLabel(item) {
  return { proposal: 'Approve AI fix', confirm: 'Confirm fix', author: 'Approve description' }[reviewType(item)]
    || 'Approve'
}

// Suggested-outline scaffold for authoring from scratch (no AI draft) — bullets that turn a blank
// box into a guided task, so a reviewer is never staring at "good luck". SC-aware; null when the
// field is self-explanatory (the placeholder alone suffices).
const _SCAFFOLD = {
  '1.1.1': ['What kind of image is it? (photo, chart, diagram, logo)',
            'What information does it convey? Lead with that.',
            'Skip decorative colour and styling.',
            'Describe the meaning, not just the picture.'],
  '2.4.4': ['Say where the link goes or what it does.',
            'Make it meaningful out of context — not “click here”.'],
  '2.4.9': ['Say where the link goes or what it does.',
            'Make it meaningful out of context — not “click here”.'],
  '1.3.3': ['Name the control by its label, not its position or colour.',
            'e.g. “Select the Save button”, not “the green button on the right”.'],
  '4.1.2': ['Give the field the label a screen reader should announce.',
            'e.g. “Home address”, “Date of birth”.'],
}
export function authoringScaffold(sc) { return _SCAFFOLD[String(sc || '')] || null }

// The WCAG exception a reviewer may APPLY on an images-of-text finding (1.4.5 / 1.4.9), routed by the
// detected image KIND (#130 describedImageType — the model's own words, never guessed). The only
// standard exemption here is a logotype / brand mark, so "Is this a logo?" is the right question for a
// logo or an unidentified image — but it reads as nonsense on a DATA image. A chart's baked-in text is
// NOT essential: it should be provided as real, selectable text (a chart, additionally, as an
// accessible data table), so a recognised content kind (chart / diagram / screenshot / table / map /
// photo / illustration) gets honest remediation guidance and NO exempt button — offering one would let
// real data be waved through as "essential". Kind unknown → keep the exemption option (a short baked-in
// text block is very often a brand mark; we can't rule it out). Returns null off these criteria, else
// { kind, prompt, action:{label,title,resolution} } for the exemption path or { kind, note } for the
// content-remediation path.
const _CONTENT_IMAGE_KINDS = new Set(['Chart', 'Diagram', 'Screenshot', 'Table', 'Map', 'Photo', 'Illustration'])
export function imagesOfTextException(sc, imgKind) {
  if (sc !== '1.4.5' && sc !== '1.4.9') return null
  const label = imgKind && imgKind.label
  if (label && _CONTENT_IMAGE_KINDS.has(label)) {
    const noun = label.toLowerCase()
    return {
      kind: label,
      note: label === 'Chart'
        ? 'This is a chart, not a logo — the logotype exemption doesn’t apply. Provide its text as real, selectable text or an accessible data table, not baked into an image.'
        : `This ${noun} contains text and isn’t a logo — the logotype exemption doesn’t apply. Provide the text as real, selectable text rather than an image.`,
    }
  }
  return {
    kind: label || null,
    prompt: 'Is this a logo or brand mark? Essential images of text are exempt.',
    action: {
      label: '🏷️ Essential logo/brand — exempt',
      title: 'Resolve as essential — a logo/brand mark is exempt from the images-of-text rule (WCAG 1.4.5/1.4.9). Recorded as an exception, not a fix.',
      resolution: 'essential_exception',
    },
  }
}

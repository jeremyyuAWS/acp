import { useState, useEffect, useMemo, useRef } from 'react'
import { aiProvenance, getFileGeometry, getFileRemediationDiffs, getScanAiCalls, suggestFix, validateAlt } from './api.js'
import Thumbnail from './Thumbnail.jsx'
import { buildEvidenceCard, describedImageType, evidenceOf, evidenceSignals, explainFinding, firstProposed, groupPages, isValueFix, proposalsOf, reviewTelemetry, thumbAlt, thumbSize, trustStates, validationChecklist, verificationLadder, whyHumanReview } from './reviewCard.js'
import ProposalThumb from './ProposalThumb.jsx'
import ProposalEditors, { seedValues } from './ProposalEditors.jsx'
import HowToConfirm from './HowToConfirm.jsx'

// Evidence Card (PRD v2) — a PR-style review of ONE accessibility issue. The human APPROVES
// ACP's recommendation; ACP applies it. Assembles only shipped primitives (confidence basis,
// remediationTrack, remediation_diff, thumbnail) and records review telemetry (edited flag +
// review time) so the workspace can report reviewer time saved and calibrate confidence.
//
// onAct(id, status, note, approvedValue, telemetry) — the parent owns the write, so its
// optimistic update and the queue-drain event stay wired. traceUrl is optional.
// Trust-state pill styling (ADR 0019) — a verifiable state, never a confidence colour-by-score.
const _TRUST_BG = { ok: '#E1F5EE', warn: '#FAEEDA', todo: 'rgba(0,0,0,.05)' }
const _TRUST_FG = { ok: '#0F6E56', warn: '#854F0B', todo: '#6b6b6b' }
const trustPill = (tone) => ({ padding: '2px 9px', borderRadius: 6, fontSize: 12, whiteSpace: 'nowrap',
  background: _TRUST_BG[tone] || _TRUST_BG.todo, color: _TRUST_FG[tone] || _TRUST_FG.todo })
const trustIcon = (tone) => (tone === 'ok' ? '✓' : tone === 'warn' ? '◐' : '○')

export default function EvidenceCard({ item, onAct, onResolved, traceUrl = null }) {
  const [diffs, setDiffs] = useState([])
  // One editor per proposal: the row carries one proposal per image, and a single text box
  // could never describe ten different pictures. Seeded from each image's own draft, so
  // approving without touching anything means "the drafts I was shown are correct" — the
  // server applies exactly these, per locator.
  const proposalList = proposalsOf(item)
  // Prefill from the server-side AI proposal when there is one — that is what turns a 30s
  // "write the alt text" into a 5s "confirm this". Falls back to a previously-approved value.
  const [value, setValue] = useState(firstProposed(item) ?? item?.approved_value ?? '')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  // A decision the server refused. Rendered as an alert — a silent failure here is a
  // reviewer believing they signed something off that was never recorded.
  const [actError, setActError] = useState(null)
  const [showExplain, setShowExplain] = useState(false)   // "✨ Explain this finding" toggle
  const [showAudit, setShowAudit] = useState(false)       // "🔎 AI audit trail" toggle (#129)
  const [aiCalls, setAiCalls] = useState(null)            // null = unloaded, [] = loaded-empty
  const [drafting, setDrafting] = useState(false)
  const [draftMsg, setDraftMsg] = useState(null)   // { kind: 'ai' | 'template' | 'error', text }
  // Which deferred image the reviewer is looking at. The vision model describes ONE image, so
  // a row carrying nineteen must say which — defaulting to the first silently captions the
  // wrong picture and the reviewer approves alt text for an image they never saw.
  const evidence = evidenceOf(item)
  // The per-image editors are driven by proposals when the AI drafted any. When it drafted none
  // — a DEFERRED 1.1.1 row that carries only `evidence` thumbnails — the same editors are driven
  // by the evidence instead, so a deck's nineteen undescribed images each get a box rather than a
  // picker that could only ever record one value. Evidence has no draft, hence proposed_value ''.
  const usingEvidence = proposalList.length === 0 && evidence.length > 0
  const instances = proposalList.length
    ? proposalList
    : evidence.map((e) => ({ locator: e.locator, thumb: e.thumb, proposed_value: '',
                             approved_value: e.approved_value }))
  const [values, setValues] = useState(() => seedValues(instances))
  const setValueAt = (i, v) => setValues((prev) => prev.map((x, j) => (j === i ? v : x)))
  // Approve-similar (#132): copy row i's description to every instance that is the SAME image
  // (byte-identical thumbnail) — a logo reused across slides gets described once.
  const applyToSimilar = (i) => {
    const t = instances[i]?.thumb
    if (!t) return
    setValues((prev) => prev.map((x, j) => (instances[j]?.thumb === t ? prev[i] : x)))
  }
  // Cross-check the CURRENT value of image i against a fresh independent description (#123). Returns
  // the verdict so ProposalEditors can show it inline. Best-effort → null on any failure.
  const crossCheck = (i) => {
    if (!item?.scan_id || !item?.file || !item?.rule_id) return Promise.resolve(null)
    return validateAlt(item.scan_id, item.file, item.rule_id, instances[i]?.locator, values[i])
      .then((v) => (v && v.verdict ? v : null))
      .catch(() => null)
  }
  const [draftingIdx, setDraftingIdx] = useState(null)
  // Which flagged image the HERO is showing (#122 multi-image pager). A 1.1.1 row can carry many
  // undescribed images across several slides; the pager steps the large preview + its bounding box
  // through each one, so a reviewer verifies every finding in place, not just the first.
  const [heroIdx, setHeroIdx] = useState(0)
  // Page heatmap (#121 / vision §17): which pages/slides the flagged objects live on, from
  // MEASURED geometry only (the same bbox lookup the hero overlay uses — never guessed). A
  // multi-image finding renders a clickable page strip; a page the geometry can't attribute
  // simply doesn't appear. instances is rebuilt every render, so the fetch keys on the stable
  // locator signature instead.
  const [pageMap, setPageMap] = useState({})       // instance idx -> page number
  const locatorSig = instances.map((x) => x?.locator || '').join('|')
  useEffect(() => {
    setPageMap({})
    if (!item?.scan_id || !item?.file || instances.length < 2) return
    let live = true
    instances.forEach((inst, i) => {
      if (!inst?.locator) return
      getFileGeometry(item.scan_id, item.file, inst.locator)
        .then((b) => { if (live && b && b.page) setPageMap((m) => ({ ...m, [i]: b.page })) })
    })
    return () => { live = false }
  }, [item?.scan_id, item?.file, locatorSig]) // eslint-disable-line react-hooks/exhaustive-deps
  const pageStrip = useMemo(() => groupPages(pageMap), [pageMap])
  const shownAt = useRef(Date.now())               // reviewer-time metric starts when the card mounts
  // The value the AI actually proposed — reviewTelemetry diffs the human's final value against
  // this to derive the `edited` calibration signal, so it must be the proposal, not the draft.
  const aiDraft = useRef(firstProposed(item) ?? item?.approved_value ?? null)

  useEffect(() => {
    let live = true
    if (item?.scan_id && item?.file) {
      getFileRemediationDiffs(item.scan_id, item.file).then((r) => { if (live) setDiffs(r || []) }).catch(() => {})
    }
    return () => { live = false }
  }, [item?.scan_id, item?.file])

  // Draft on demand. Most items reach the inbox with a server-side proposal already attached,
  // but an image whose alt text the vision model could not produce arrives with nothing — and
  // the reviewer had no way to ask for one. This is that ask.
  const draftWithAi = async () => {
    if (!item?.scan_id || !item?.file || !item?.rule_id) return
    setDrafting(true); setDraftMsg(null)
    try {
      // This box is only shown for a single value-fix finding with no proposals and no evidence
      // (e.g. one link-text finding), so there is no per-image locator to pass — a deferred image
      // row uses draftInstance instead. evidence[0] is undefined here, which is correct.
      const r = await suggestFix(item.scan_id, item.file, item.rule_id, evidence[0]?.locator)
      const s = (r?.suggestion || '').trim()
      if (!s) { setDraftMsg({ kind: 'error', text: 'The model returned nothing — write the value yourself.' }); return }
      setValue(s)
      if (r.is_template) {
        // A fill-in-the-blank template, NOT a description of this image. It is deliberately
        // NOT recorded as aiDraft: approving it verbatim must count as human-authored, and
        // reviewTelemetry must not log a template as an accepted AI value. Say WHY it is a
        // template — "no vision model described this image" read as "llava looked and failed"
        // even when no vision model was ever consulted.
        setDraftMsg({ kind: 'template', text: r.reason || 'Template only — no vision model was available to look at this image. Rewrite it before approving.' })
      } else {
        aiDraft.current = s   // a genuine AI value: `edited` now means the human changed it
        setDraftMsg({ kind: 'ai', text: `AI draft${r.model ? ` · ${r.model}` : ''} — edit if it misses the meaning.` })
      }
    } catch (e) {
      setDraftMsg({ kind: 'error', text: e?.message || 'AI draft unavailable — write the value yourself.' })
    } finally {
      setDrafting(false)
    }
  }

  // Draft one deferred image, by its own row. Unlike draftWithAi (single box), this writes the
  // result into instance i's value — the model saw image i, so its description belongs to image i.
  const draftInstance = async (i, style = '') => {
    if (draftingIdx != null || !item?.scan_id || !item?.file || !item?.rule_id) return
    setDraftingIdx(i); setDraftMsg(null)
    try {
      const r = await suggestFix(item.scan_id, item.file, item.rule_id, instances[i]?.locator, style || null)
      const s = (r?.suggestion || '').trim()
      if (!s) { setDraftMsg({ kind: 'error', text: `Image ${i + 1}: the model returned nothing — write it yourself.` }); return }
      setValueAt(i, s)
      const styleWord = style === 'shorter' ? ' (shorter)' : style === 'detailed' ? ' (more detail)' : style === 'regenerate' ? ' (regenerated)' : ''
      setDraftMsg(r.is_template
        ? { kind: 'template', text: r.reason || 'Template only — no vision model was available. Rewrite it before approving.' }
        : { kind: 'ai', text: `Image ${i + 1} drafted${styleWord}${r.model ? ` · ${r.model}` : ''} — edit if it misses the meaning.` })
    } catch (e) {
      setDraftMsg({ kind: 'error', text: e?.message || 'AI draft unavailable — write the value yourself.' })
    } finally {
      setDraftingIdx(null)
    }
  }

  const card = buildEvidenceCard(item, diffs)
  // Everything about the "current" image follows the pager (#122) so the hero box, the object thumb,
  // and the kind chip all describe the SAME image — paging to image 3 must not leave image 1's thumb
  // beside the text. All fall back to the card's first instance for a single-image finding.
  const heroInst = instances[heroIdx] || null
  const heroLocator = heroInst?.locator || card.locator
  const heroThumb = heroInst?.thumb ?? card.thumb
  // The kind of image, read from the model's own description (#130) — a routing hint for what a
  // good alt text looks like here (a chart needs a trend, an icon two words). null → no chip.
  const imgKind = describedImageType(heroInst ? { proposals: [heroInst] } : item)
  // Reviewer-trust primitives (all derived from real fields — never a fabricated score):
  //   ladder  — how far the pipeline got before handing off (detected → validated → your approval)
  //   signals — the concrete evidence behind the finding (detection basis, reasoning, subjective flag)
  const ladder = verificationLadder(card)
  const signals = evidenceSignals(card)
  const whyReview = whyHumanReview(card)
  // AI provenance (ADR 0019 Phase 0): which model produced this + where the bytes were processed.
  const aiProv = aiProvenance()

  // The AI audit trail (#129) — the real per-call provenance ledger, lazily fetched on first open
  // and narrowed to this file. Every row is a logged model call (surface/model/zone/latency), so the
  // reviewer (and an auditor) can see exactly what ran, where, and how long — no fabrication.
  const toggleAudit = () => {
    setShowAudit((s) => !s)
    if (aiCalls === null && item?.scan_id) {
      getScanAiCalls(item.scan_id)
        .then((r) => setAiCalls(Array.isArray(r) ? r : []))
        .catch(() => setAiCalls([]))
    }
  }
  const auditRows = (aiCalls || []).filter((c) => !c.file || c.file === item?.file)
  // Verifiable trust states (ADR 0019 §3a) — grounding + validation, the evidence-based replacement
  // for a confidence label. No number, no opaque level; the review-requirement axis is whyReview.
  const trust = trustStates(card)
  // Deterministic, keyless plain-English explanation (the "✨ Explain this finding" answer).
  const explanation = explainFinding(card, { trust, whyReview })
  // Deterministic-validation receipt (vision #12) — the machine-verified proof for an APPLIED fix,
  // shown separately from the AI generation. Null until something is applied + re-scan-cleared.
  const valChecklist = validationChecklist(card)
  // Cluster the evidence by group (Detection / Reasoning / Document state) in a stable order — the
  // way a reviewer scans it — rather than one flat list.
  const signalGroups = signals.reduce((m, s) => { (m[s.group] = m[s.group] || []).push(s); return m }, {})
  const GROUP_ORDER = ['Detection', 'Document state', 'Reasoning']
  // An editor appears for every value-fix criterion, draft or not — a reviewer must be able to
  // author alt text the AI could not draft. Keying off `aiDraft != null` (as this once did)
  // silently hid the box exactly when the human was most needed.
  // An item carrying a proposal always takes a value, even if its SC isn't a classic VALUE_FIX
  // (e.g. a 1.3.3 sensory rewrite) — otherwise the reviewer sees a proposal they cannot accept.
  const editable = card.track.track !== 'auto' && (isValueFix(card.sc) || !!card.proposal)
  // What approving actually does, in three honest cases:
  //   judgement (contrast)      → the sign-off IS the resolution        → the track's own verb
  //   content WITH an applier   → the value is written into the document → say so
  //   content with no applier   → the value is recorded, nothing written → say that instead
  // Alt text on an Office file is the only thing ACP can write back today (api/apply_alt.py).
  const hasApplier = card.sc === '1.1.1' && /\.(docx|pptx|xlsx)$/i.test(card.file || '')
  const primaryLabel = card.certifiesOnApprove
    ? card.track.action
    : hasApplier ? 'Approve & write into the document' : 'Approve — record sign-off'
  // Any row carrying proposals gets the per-instance editor. It is the only surface that shows
  // WHAT is changing — the image, or the passage of text — beside the value being written, and
  // a reviewer cannot honestly approve a description of something they were never shown.
  // Per-instance editors render for a row with proposals (drafted images) OR a deferred row with
  // evidence (undrafted images) — either way `instances` has the entries and `values` is
  // positionally aligned with them.
  const multi = instances.length > 0
  // Only a row with many findings and NO per-image instances at all still can't be expressed in
  // one box — keep warning rather than implying it can. (Now rare: deferred rows carry evidence.)
  const manyInstances = !multi && card.findingCount > 1 && isValueFix(card.sc)

  const decide = async (status) => {
    if (busy) return
    setBusy(true)
    setActError(null)
    // The headline value (audit log, telemetry) is the first image's text when the row carries
    // proposals — the same one the collapsed card shows.
    const headline = multi ? (values[0] || '') : value
    const t = reviewTelemetry({
      editable, status, value: headline, aiDraft: aiDraft.current,
      elapsedMs: Date.now() - shownAt.current,
    })
    // What actually gets written into the document, one entry per image, positionally aligned
    // with `instances` (proposals or deferred evidence). Only on approval: rejecting approves no
    // content. The server routes these to proposals[] or evidence[] as the row demands.
    const approvedValues = (status === 'approved' && instances.length)
      ? (multi ? values : [value || ''])
      : null
    try {
      await onAct(card.id, status, note || null, t.finalValue,
                  { edited: t.edited, reviewMs: t.reviewMs, aiValue: t.aiValue, approvedValues })
      onResolved && onResolved(card.id, status)
    } catch (e) {
      // HitlBell rolls the optimistic list back and rethrows. Without this catch the rejection
      // was unhandled: the reviewer saw the card sit there with no error, having signed off on
      // nothing. An unrecorded approval must never look like a recorded one.
      setActError(`Not saved: ${e?.message || e}. Nothing was recorded — try again.`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="evcard" aria-label={`Review ${card.wcag}`}
             style={{ border: '1px solid var(--line)', borderRadius: 10, padding: 14, marginBottom: 12, background: 'var(--card, #fff)' }}>
      <header className="evcard-hd" style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span className="fmtchip">{card.fmt}</span>
        <b className="evcard-wcag">{card.wcag}</b>
        <span className="muted">{card.name}</span>
        {/* Where to look. Rendered only when the analysers attributed a page — the reviewer
            gets no location rather than a wrong one. */}
        {card.location && (
          <span className="evcard-loc muted" title={`This criterion fails on ${card.location.toLowerCase()}`}>
            📍 {card.location}
          </span>
        )}
        <span className={`conf conf-${card.track.badge.tone}`} style={{ marginLeft: 'auto' }}>{card.track.badge.label}</span>
      </header>

      {/* Verification ladder — the honest lifecycle of this finding. Each step reflects a real
          pipeline state; a value-fix reads "validates on approval" (not a green pass) because the
          write + re-scan happen when you approve, so the card never claims a fix the doc still lacks. */}
      <div className="evcard-ladder" style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', margin: '0 0 12px' }}>
        {ladder.map((s, i) => (
          <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            {i > 0 && <span className="muted" aria-hidden="true">→</span>}
            <span className={s.state === 'done' ? 'conf conf-high' : s.state === 'current' ? 'conf conf-medium' : 'conf'}
                  style={s.state === 'todo' ? { opacity: 0.55 } : undefined}>
              {s.state === 'done' ? '✓ ' : s.state === 'current' ? '● ' : ''}{s.label}
            </span>
          </span>
        ))}
      </div>

      {/* Large page preview (ADR 0018) — the visual "where": the finding's page rendered big, the
          hero of the card (Principle 2). Self-hides when the backend can't rasterize (Thumbnail
          returns null): PDF always; Office (pptx/docx/xlsx) once LibreOffice is in the image. The
          bounding-box overlay pinpointing the object is the next slice (needs per-shape geometry). */}
      {card.scanId && card.file && (
        <div className="evcard-hero" style={{ margin: '0 0 12px' }}>
          {instances.length > 1 && (
            <div className="evcard-hero-pager">
              <button type="button" aria-label="Previous flagged image"
                      onClick={() => setHeroIdx((i) => (i - 1 + instances.length) % instances.length)}>‹</button>
              <span>Image {heroIdx + 1} of {instances.length}</span>
              <button type="button" aria-label="Next flagged image"
                      onClick={() => setHeroIdx((i) => (i + 1) % instances.length)}>›</button>
            </div>
          )}
          {/* Document heatmap (vision §17): the pages that carry findings, with counts — click to
              jump the hero straight to that page's first finding. Only rendered when geometry
              attributed 2+ pages (a single-page finding needs no map). */}
          {pageStrip.length > 1 && (
            <div className="evcard-pagestrip" aria-label="Pages with findings">
              <span className="muted">On pages:</span>
              {pageStrip.map(([p, idxs]) => (
                <button key={p} type="button"
                        className={`evcard-pagechip${pageMap[heroIdx] === p ? ' evcard-pagechip-on' : ''}`}
                        title={`${idxs.length} finding${idxs.length > 1 ? 's' : ''} on page/slide ${p} — click to jump`}
                        onClick={() => setHeroIdx(idxs[0])}>
                  {p}<span className="evcard-pagechip-n">{idxs.length}</span>
                </button>
              ))}
            </div>
          )}
          <Thumbnail scanId={card.scanId} file={card.file} page={card.page || 1} locator={heroLocator} maxHeight={360} />
        </div>
      )}

      <div className="evcard-body" style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        {/* The specific object under review — the offending image beside the text. Follows the pager
            (#122) so it's the SAME image the hero boxes above. The whole-page context is the hero
            preview; this is the "what". */}
        {heroThumb && (
          <ProposalThumb thumb={heroThumb} alt={thumbAlt(card.thumbKind, card.file)}
                         size={thumbSize(card.thumbKind, 96)} className="evcard-thumb" />
        )}
        <div className="evcard-main" style={{ flex: 1, minWidth: 0 }}>
          <p className="evcard-problem">{card.problem}</p>
          {/* Image-kind routing hint (#130) — the model's own noun for what this is, with a hint on
              what a good description looks like for that kind. Honest: derived from the description,
              shown only when a kind is recognised. */}
          {imgKind && (
            <div className="evcard-imgkind" title={`Read from the AI description — ${imgKind.hint}`}>
              <span className="evcard-imgkind-tag">{imgKind.icon} {imgKind.label}</span>
              <span className="muted">{imgKind.hint}</span>
            </div>
          )}

          {/* "✨ Explain this finding" — a deterministic, keyless plain-English primer (what the
              criterion requires, who is blocked, what ACP drafted + how anchored, why you're here).
              Composed from real catalog + finding fields; no model call, no fabricated number. */}
          {explanation && (
            <div className="evcard-explain" style={{ margin: '2px 0 8px' }}>
              <button type="button" className="evcard-explain-btn"
                      aria-expanded={showExplain}
                      onClick={() => setShowExplain((v) => !v)}>
                {showExplain ? '× Hide explanation' : '✨ Explain this finding'}
              </button>
              {showExplain && (
                <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.55, margin: '7px 0 0',
                     padding: '9px 11px', background: 'var(--surface-1, #f6f5f2)',
                     border: '1px solid var(--line)', borderRadius: 8 }}>
                  {explanation}
                </p>
              )}
            </div>
          )}

          {/* Deferred images (evidence, no AI draft) now render through ProposalEditors below —
              one editable row per image, each with its own "Draft with AI". The old thumbnail
              picker fed one shared textarea, so it could record only a single value; it is gone. */}

          {editable && multi ? (
            <>
              <ProposalEditors proposals={instances} values={values} sc={card.sc}
                               onChange={setValueAt} file={card.file}
                               onDraft={usingEvidence ? draftInstance : undefined}
                               draftingIdx={usingEvidence ? draftingIdx : null}
                               onApplyToSimilar={applyToSimilar} onCrossCheck={crossCheck} />
              {usingEvidence && draftMsg && (
                <span className={`evcard-draft-msg evcard-draft-${draftMsg.kind}`} role="status">
                  {draftMsg.text}
                </span>
              )}
            </>
          ) : editable ? (
            <label className="evcard-rec">
              <span className="evcard-rec-head">
                <span className="muted" style={{ fontSize: 12 }}>
                  {aiDraft.current ? 'AI recommendation (edit before approving if needed)' : 'No AI draft — type the value a screen reader should announce'}
                </span>
                {/* Ask the model for a draft on demand. Only offered when nothing was proposed —
                    with a proposal present the box is already filled and re-drafting would
                    silently overwrite the value the rationale below explains. */}
                {!aiDraft.current && item?.scan_id && item?.file && item?.rule_id && (
                  <button type="button" className="evcard-draft-btn" disabled={drafting}
                          title="Ask the local model to draft this value — you still approve it"
                          onClick={draftWithAi}>
                    {drafting ? 'Drafting…' : '✨ Draft with AI'}
                  </button>
                )}
              </span>
              <textarea className="evcard-rec-input" rows={2} value={value}
                        placeholder={aiDraft.current ? '' : 'Type the value a screen reader should announce…'}
                        onChange={(e) => setValue(e.target.value)} />
              {draftMsg && (
                <span className={`evcard-draft-msg evcard-draft-${draftMsg.kind}`} role="status">
                  {draftMsg.text}
                </span>
              )}
            </label>
          ) : card.recommendation ? (
            <p className="evcard-rec-static"><b>AI recommendation:</b> {card.recommendation}</p>
          ) : null}

          {/* Trust basis (ADR 0019 §3a) — verifiable states, NOT a confidence score. Grounding = what
              the value is anchored in (OCR / document text / a visual guess); Validation = whether an
              objective check has actually passed. The review-requirement axis is the "Why human
              review?" callout below. No number, no opaque level. */}
          {(trust.grounding || trust.validation) && (
            <div className="evcard-trust" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', margin: '4px 0 8px' }}>
              {trust.grounding && (
                <span style={trustPill(trust.grounding.tone)} title="Grounding — what the value is anchored in">{trustIcon(trust.grounding.tone)} {trust.grounding.label}</span>
              )}
              <span style={trustPill(trust.validation.tone)} title="Validation — whether an objective check has passed">{trustIcon(trust.validation.tone)} {trust.validation.label}</span>
              {trust.review && (
                <span style={trustPill(trust.review.tone)} title="Review requirement — why a human is (or isn’t) needed">{trustIcon(trust.review.tone)} {trust.review.label}</span>
              )}
              {card.proposal && card.proposal.list.length > 1 && (
                <span className="muted" style={{ fontSize: 12 }}>· {card.proposal.list.length} instances on this criterion</span>
              )}
            </div>
          )}

          {/* AI provenance (ADR 0019 Phase 0) — don't hide the model. Names the model that produced
              this value (from the proposal's own source, or the active model) and, from the real
              backend config, WHERE the bytes were processed: 🟢 local = on your own infrastructure,
              nothing left your network. Shown only where AI actually generated a value. */}
          {(card.proposal || card.recommendation) && aiProv && (
            <div className="evcard-provenance" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 12, margin: '2px 0 8px' }}>
              <span className="muted">🤖 {card.proposalSource || `${aiProv.provider} · ${card.sc === '1.1.1' ? aiProv.vision_model : aiProv.model}`}</span>
              <span style={{ padding: '2px 8px', borderRadius: 6, fontSize: 11.5, whiteSpace: 'nowrap',
                   background: aiProv.zone === 'local' ? '#E1F5EE' : '#FAEEDA',
                   color: aiProv.zone === 'local' ? '#0F6E56' : '#854F0B' }}>
                {aiProv.zone === 'local' ? '🟢 Local only' : '🟡 Cloud'}
              </span>
              <span className="muted">{aiProv.zone === 'local'
                ? 'processed on your infrastructure — no document left your network'
                : `sent to ${aiProv.host}`}</span>
              {item?.scan_id && (
                <button type="button" className="evcard-audit-btn" aria-pressed={showAudit}
                        onClick={toggleAudit}>
                  {showAudit ? 'Hide audit trail' : '🔎 AI audit trail'}
                </button>
              )}
            </div>
          )}

          {/* The AI audit trail (#129) — the real ledger of model calls for THIS file: what model
              ran, on which surface, in which privacy zone, how long it took, and whether it
              succeeded. Every row is a persisted ai_calls record (ADR 0019 Phase 0b) — nothing here
              is fabricated; an empty ledger says so honestly rather than inventing activity. */}
          {showAudit && (
            <div className="evcard-audit" style={{ margin: '2px 0 10px' }}>
              {aiCalls === null ? (
                <div className="muted" style={{ fontSize: 12 }}>Loading audit trail…</div>
              ) : auditRows.length === 0 ? (
                <div className="muted" style={{ fontSize: 12 }}>
                  No AI calls recorded for this file — it was handled deterministically (no model saw it).
                </div>
              ) : (
                <table className="evcard-audit-table">
                  <thead>
                    <tr><th>Surface</th><th>Model</th><th>Zone</th><th>Latency</th><th>Result</th></tr>
                  </thead>
                  <tbody>
                    {auditRows.map((c, i) => (
                      <tr key={c.id || i}>
                        <td>{c.surface || '—'}</td>
                        <td>{c.provider ? `${c.provider} · ${c.model}` : (c.model || '—')}</td>
                        <td><span className={`audit-zone audit-zone-${c.zone === 'local' ? 'local' : 'cloud'}`}>
                          {c.zone === 'local' ? '🟢 local' : '🟡 cloud'}</span></td>
                        <td>{Number.isFinite(c.latency_ms) ? `${(c.latency_ms / 1000).toFixed(1)}s` : '—'}</td>
                        <td>{c.ok === false ? '✗ failed' : '✓ ok'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* The evidence behind the finding — concrete, checkable signals the pipeline produced,
              CLUSTERED (Detection / Document state / Reasoning) the way a reviewer scans them, never
              an invented score. An empty group is skipped. */}
          {signals.length > 0 && (
            <div className="evcard-evidence" style={{ margin: '2px 0 8px' }}>
              {GROUP_ORDER.filter((g) => signalGroups[g]).map((g) => (
                <div key={g} style={{ margin: '0 0 6px' }}>
                  <div className="muted" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '.04em', margin: '0 0 2px' }}>{g}</div>
                  {signalGroups[g].map((s, i) => (
                    <div key={i} style={{ display: 'flex', gap: 7, alignItems: 'flex-start', fontSize: 12, margin: '2px 0' }}>
                      <span aria-hidden="true" style={{ color: s.tone === 'warn' ? '#BA7517' : '#0F6E56', flexShrink: 0 }}>{s.tone === 'warn' ? '⚠' : '✓'}</span>
                      <span className="muted">{s.text}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}

          {/* "Why am I reviewing this?" — the honest reason a human is in the loop for this finding,
              so the reviewer understands the ask before approving. Null → nothing shown. */}
          {whyReview && (
            <div className="evcard-whyreview" style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 12.5,
                 background: '#FAEEDA', border: '1px solid var(--line)', borderRadius: 8, padding: '8px 11px', margin: '0 0 8px' }}>
              <span aria-hidden="true" style={{ color: '#854F0B' }}>❓</span>
              <span><b>Why human review?</b> {whyReview}</span>
            </div>
          )}

          {card.diffs.length > 0 && (
            <div className="evcard-ba">
              {card.diffs.slice(0, 1).map((d, i) => (
                <div key={i}>
                  <div className="diffbox before"><span className="difftag">before</span>{d.before}</div>
                  <div className="diffbox after"><span className="difftag">after</span>{d.after}</div>
                </div>
              ))}
            </div>
          )}

          {/* Deterministic validation (vision #12/#33) — the machine-verified receipt for an applied
              fix, kept DISTINCT from the AI-written value above. Every ✓ is a real fact (a
              remediation_diff / validated proposal proves write + re-open + re-scan + clear), never
              a bare "Done". Absent until something is actually applied + verified. */}
          {valChecklist && (
            <div className="evcard-valcheck" style={{ margin: '2px 0 8px', padding: '9px 11px',
                 background: '#E1F5EE', border: '1px solid var(--line)', borderRadius: 8 }}>
              <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '.04em', color: '#0F6E56', margin: '0 0 4px' }}>Deterministic validation</div>
              {valChecklist.map((v, i) => (
                <div key={i} style={{ display: 'flex', gap: 7, alignItems: 'flex-start', fontSize: 12.5, margin: '2px 0', color: '#0F6E56' }}>
                  <span aria-hidden="true">✓</span><span>{v.label}</span>
                </div>
              ))}
            </div>
          )}

          {/* What approval actually does. A judgement sign-off resolves the criterion; a
              value-fix approval only records evidence — ACP has no write-back yet, so the
              criterion keeps failing until the file is fixed and re-scanned. */}
          {card.certifiesOnApprove ? (
            <p className="evcard-impact muted" style={{ fontSize: 12 }}>
              Compliance: <span className="conf conf-low">{card.impact.before}</span> → <span className="conf conf-high">{card.impact.after}</span> after approval
            </p>
          ) : (
            <div className="evcard-todo">
              <b>What you need to do</b>
              {manyInstances ? (
                <p>
                  These <b>{card.findingCount} images</b> each need their own description — one sentence
                  cannot describe them all. Open the file, write alt text on each image, then
                  <b> ✋ I’ll fix it</b> to re-scan and confirm.
                </p>
              ) : (
                <p>
                  Write the text a screen reader should announce, then approve it. ACP records
                  your value as compliance evidence.
                </p>
              )}
              <p className="muted">
                Approving records your sign-off — it does <b>not</b> write the value into the document,
                so <span className="conf conf-low">{card.sc}</span> keeps failing until the file is
                fixed and re-scanned.
              </p>
            </div>
          )}

          {/* How the reviewer confirms the fix in the native app — the "verify it yourself in
              under 10s" half of the trust model. Renders per-criterion Word/Excel/PowerPoint/
              Acrobat steps (Mac/Win), or only the universal Accessibility-Checker line when no
              crisp native step exists; nothing at all when neither applies (never a wrong path). */}
          <HowToConfirm sc={card.sc} file={card.file} />

          {/* Certification preview — the auditor-facing entry this review will produce, assembled
              from what's already on the card (no new endpoint). The reviewer + timestamp are
              stamped on approval, so it says "on approval" rather than pre-filling a fake signer. */}
          {(card.thumb || card.recommendation || value) && (
            <details className="evcard-cert" style={{ margin: '0 0 8px' }}>
              <summary style={{ fontSize: 13, cursor: 'pointer', color: 'var(--muted, #666)' }}>
                📄 What the certification report will record
              </summary>
              <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', marginTop: 8, padding: '9px 11px',
                   border: '1px solid var(--line)', borderRadius: 8, background: 'var(--surface-1, #f6f5f2)' }}>
                {card.thumb && <ProposalThumb thumb={card.thumb} alt="" size={40} />}
                <div style={{ fontSize: 12, minWidth: 0 }}>
                  <div><b>{card.wcag}</b> · {card.file}{card.location ? ` · ${card.location}` : ''}</div>
                  {(value || (multi && values[0]) || card.recommendation) && (
                    <div className="muted" style={{ margin: '3px 0', wordBreak: 'break-word' }}>Value: “{value || (multi && values[0]) || card.recommendation}”</div>
                  )}
                  <div><span className="conf conf-high">Verified</span> <span className="muted">on approval · signed off by you</span></div>
                </div>
              </div>
            </details>
          )}

          <input className="rc-note" placeholder="Reviewer note (optional)" value={note}
                 onChange={(e) => setNote(e.target.value)} />

          {/* Beside the buttons that failed, not in a corner. role=alert so a screen-reader
              user is told too — this card is the accessibility product's own review surface. */}
          {actError && (
            <p role="alert" className="evcard-act-error"
               style={{ margin: '0 0 8px', padding: '9px 11px', borderRadius: 8, fontSize: 13,
                        background: '#FDECEC', color: '#8A1F1F', border: '1px solid #E9A8A8' }}>
              {actError}
            </p>
          )}

          <div className="evcard-actions">
            <button className="qbtn approve" disabled={busy} onClick={() => decide('approved')}>✓ {primaryLabel}</button>
            <button className="qbtn self" disabled={busy}
                    title="Take ownership — fix it yourself, then re-scan to confirm"
                    onClick={() => decide('skipped')}>✋ I’ll fix it</button>
            <button className="qbtn reject" disabled={busy} onClick={() => decide('rejected')}>✕ Reject</button>
            {traceUrl && <a className="rc-trace" href={traceUrl} target="_blank" rel="noopener noreferrer">📊 View trace</a>}
          </div>
        </div>
      </div>
    </section>
  )
}

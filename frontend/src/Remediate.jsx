import { useState, useEffect, useMemo, useRef } from 'react'
import { Bars } from './charts.jsx'
import ReviewDrawer from './ReviewDrawer.jsx'
import EvidenceCard from './EvidenceCard.jsx'
import FileDrawer, { REC_STYLE, fmtEffort, EFFORT_BASIS, SOURCE_URL } from './FileDrawer.jsx'
import SegmentDrawer from './SegmentDrawer.jsx'
import { recommendationSummary, SENIORITY_ORDER, REMEDIATION_ACTIONS } from './sim.js'
import { PRI_COLOR, PRI_RANK } from './ontology.js'
import { remediateScan, getRemediationStatus, downloadRemediated, autoPopulateHitlQueue, listHitlQueue, updateHitlItem, suggestFix, rescoreFile, getJob, getAppliedFixes, getScanRemediationDiffs, getHitlAnalytics, openTraceUrl } from './api.js'
import { SIM, simProposalsFor } from './sim.js'
import { TraceChip } from './Transparency.jsx'
import QueuePanel from './QueuePanel.jsx'
import { groupFixesByRule, summarizeImpact, totalFixes, scOf } from './fixSummary.js'
import { confidenceForFinding, confClass } from './confidence.js'
import { metaFor } from './hitlMeta.js'
import { firstProposed, firstBefore, firstThumb, firstKind, firstRationale, firstSource, pageOf,
         pageNoun, thumbAlt, thumbSize, appliedFixAlt, comparisonFor, noDraftHint } from './reviewCard.js'
import ProposalThumb from './ProposalThumb.jsx'
import Thumbnail from './Thumbnail.jsx'
import { remediableFiles, emptyScopeReason, scopeSummary, ineligibleReason } from './remediableScope.js'
import { measuredReviewTime, REVIEW_TIME_BASIS } from './reviewerTime.js'

// Steps 6-8: Automated Remediation + HITL + Re-validate. Owns the remediation plan
// (what to fix, prioritized, accept/reject/modify), the HITL queue, and self-remediation.
//
// The view is framed around the four decisions a compliance officer actually makes —
// Review → Approve → Verify → Publish — with the engine (worker queue, plan decisions,
// live metrics, business-risk graphs) folded behind an "Advanced" disclosure. Every count,
// confidence and risk statement traces to real pipeline data (applied-fix evidence, the
// live HITL queue, confidence.js, the recommendation model); nothing is fabricated.
const REM_ACTIONS = REMEDIATION_ACTIONS
const ACTIONS = ['auto', 'assisted', 'review', 'archive', 'keep', 'manual']
const ETA_OVERRIDE = { archive: 2, keep: 0, manual: 35, review: 10 }
const ACTION_DESC = {
  auto: 'The agent fixes these mechanically — alt text, headings, language, titles — then re-validates. No human needed.',
  assisted: 'AI proposes the fix; a human approves before publish. For critical, sensitive, contrast/link, or media (captions) findings.',
  review: 'A rule couldn’t be auto-evaluated. A reviewer confirms before the document can be certified.',
  manual: 'Unreadable source — a human must re-author or re-export the file before it can be assessed.',
}
const SR_COLOR = { Executive: '#1F5FA8', Director: '#D85A30', Manager: '#BF8C00', Staff: '#9a948f' }
const exposureOf = (f) => (f.tags || []).includes('public-facing') ? 'public-facing' : (f.tags || []).includes('high-traffic') ? 'high-traffic' : 'internal'
const EXP_COLOR = { 'public-facing': '#1F5FA8', 'high-traffic': '#D85A30', internal: '#9a948f' }
const SR_W = { Executive: 3, Director: 2, Manager: 1, Staff: 0 }
const priority = (f) => (f.tags || []).filter((t) => t === 'public-facing' || t === 'high-traffic').length * 2 + (SR_W[f.seniority] || 0) + (f.issues || []).filter((i) => i.severity === 'CRITICAL').length * 2

// AI triage: the same risk signals, surfaced as a priority tier + a plain-language reason.
const PRI = { high: ['P1 · high', '#1F5FA8', '#E2EDFB'], med: ['P2 · medium', '#854F0B', '#FAEEDA'], low: ['P3 · low', '#5F5E5A', '#EFEDEA'] }
const priTier = (f) => { const s = priority(f); return s >= 6 ? 'high' : s >= 3 ? 'med' : 'low' }
const priWhy = (f) => {
  const r = []
  if ((f.tags || []).includes('public-facing')) r.push('public-facing')
  else if ((f.tags || []).includes('high-traffic')) r.push('high-traffic')
  if (f.seniority === 'Executive' || f.seniority === 'Director') r.push(`${f.seniority.toLowerCase()}-owned`)
  const crit = (f.issues || []).filter((i) => i.severity === 'CRITICAL').length
  if (crit) r.push(`${crit} critical finding${crit === 1 ? '' : 's'}`)
  if (!r.length) { const ser = (f.issues || []).filter((i) => i.severity === 'SERIOUS').length; r.push(ser ? `${ser} serious finding${ser === 1 ? '' : 's'}` : 'low exposure, no critical findings') }
  return r.slice(0, 2).join(' · ')
}

const FIX_WCAG_LABELS = {
  SC_1_1_1: { label: 'alt-text generated', color: '#639922' },
  SC_1_3_2: { label: 'reading order fixed', color: '#157A56' },
  SC_2_4_2: { label: 'headings / titles tagged', color: '#378ADD' },
  SC_3_1_1: { label: 'language set', color: '#726BC6' },
  SC_1_3_1: { label: 'table headers', color: '#A56814' },
}
const ITEM_ICON = { '1.1.1': '▦', '1.2.1': '🎧', '1.2.2': '🎬', '1.2.5': '🎬', '1.3.1': '⊞', '1.3.2': '¶', '1.4.3': '◑', '2.4.2': '¶', '2.4.4': '↗', '3.1.1': '✦' }
const ITEM_NAME = { '1.1.1': 'non-text content', '1.2.1': 'audio-only & video-only', '1.2.2': 'captions', '1.2.5': 'audio description', '1.3.1': 'info & relationships', '1.3.2': 'meaningful sequence', '1.4.3': 'contrast minimum', '2.4.2': 'page titled', '2.4.4': 'link purpose', '3.1.1': 'language of page' }
const ITEM_BA = {
  '1.1.1': { meta: 'AI alt text — review accuracy', before: (d) => d || 'image / chart — no alt text' },
  '1.2.1': { meta: 'transcript draft — verify accuracy', before: () => 'audio — no transcript' },
  '1.2.2': { meta: 'ASR captions — review timing & accuracy', before: () => 'video — no caption track' },
  '1.2.5': { meta: 'audio description script — needs review', before: () => 'video — no audio description' },
  '1.3.1': { meta: 'table structure — human judgement needed', before: (d) => d || 'table without header row' },
  '1.3.2': { meta: 'two plausible reading orders', before: () => 'multi-column layout — reading order ambiguous' },
  '1.4.3': { meta: 'contrast fix needs design sign-off', before: (d) => d || 'text below 4.5:1 contrast ratio' },
  '2.4.4': { meta: 'link text — needs human rewrite', before: (d) => d || 'non-descriptive link text ("click here")' },
}
const SEV_RANK = { CRITICAL: 0, SERIOUS: 1, MODERATE: 2, MINOR: 3 }
// SCs the local Ollama model can draft a concrete replacement value for (api/ai.py
// _SUGGEST_KIND). The drawer shows these as an editable AI draft instead of a static
// canned template, and persists whatever the reviewer approves (approved_value).
const AI_DRAFTABLE_SCS = new Set(['1.1.1', '2.4.4', '2.4.9'])

function dbItemToUi(it, files) {
  const sc = (it.rule_id || '').replace(/^(WCAG_?|SC_)/, '').replace(/_/g, '.')
  const ba = ITEM_BA[sc] || { meta: 'review AI proposal', before: (d) => d || 'issue found' }
  const fileRec = (files || []).find((f) => f.file === it.file) || {}
  const issue = ((fileRec.issues || []).find((i) => (i.wcag || '').replace(/^SC_/, '').replace(/_/g, '.') === sc)) || {}
  return {
    id: it.id,
    icon: ITEM_ICON[sc] || '◈',
    title: `${((it.file || '').split('.').pop() || 'DOC').toUpperCase()} · ${it.rule_name || ITEM_NAME[sc] || sc}`,
    meta: ba.meta,
    file: it.file,
    scanId: it.scan_id,
    ruleId: it.rule_id,
    aiDraftable: AI_DRAFTABLE_SCS.has(sc),
    source: fileRec.sourceName,
    rule: `WCAG ${sc}${it.rule_name ? ' — ' + it.rule_name : ITEM_NAME[sc] ? ' — ' + ITEM_NAME[sc] : ''}`,
    // The passage the fix would replace. The proposal's own `before` is the literal offending
    // text the analyser matched (`propose_language_parts` carries the actual sentence); fall
    // back to the rule's description of the defect when no proposal names one.
    before: firstBefore(it) || ba.before(issue.detail, fileRec),
    beforeLiteral: !!firstBefore(it),
    // The page the finding sits on, per the analysers (hitl_queue.page). Null when they could
    // not attribute one — the card must then not claim a page.
    page: pageOf(it),
    // The AI's actual draft, from hitl_queue.proposals — what the vision model wrote for THIS
    // image. `approved_value` only ever holds what a REVIEWER typed back (nothing writes it
    // server-side), so the old `it.approved_value || template` fell through to the template on
    // every item: "AI-generated alt text added — confirm or reword" rendered identically for
    // every image in every document, whether or not a model had said anything. There is no
    // template fallback now: null means nothing was drafted, and the card says exactly that.
    after: firstProposed(it) || it.approved_value || null,
    // Carried through so the card can build its current→remediated comparison at RENDER time.
    // The remediation_diff rows load in parallel with this queue, so a comparison baked in
    // here would be empty on first paint and never refresh.
    proposals: it.proposals,
    // The offending image itself + why the model said what it said. Null when no proposal.
    thumb: firstThumb(it),
    thumbKind: firstKind(it),
    rationale: firstRationale(it),
    proposalSource: firstSource(it),
    // Distinguishes a real model draft from the canned fallback, so the UI never labels a
    // template as a suggestion the AI made.
    hasProposal: !!firstProposed(it),
  }
}

function buildHumanQueue(files, triage = {}) {
  const hasInscope = Object.values(triage).some((v) => v === 'inscope')
  const active = files.filter((f) => !(f.remediated_at || f.drive_write_url))  // exclude already-fixed
  const candidates = hasInscope ? active.filter((f) => triage[f.file] === 'inscope') : active
  const assisted = candidates.filter((f) => (f.rec?.action === 'assisted' || f.rec?.action === 'review') && (f.issues || []).length > 0)
  // fallback: any inscope/active file with issues that isn't fully auto-fixable
  const fallback = candidates.filter((f) => (f.issues || []).length > 0 && f.rec?.action !== 'auto' && !assisted.find((a) => a.file === f.file))
  const pool = assisted.length >= 3 ? assisted : [...assisted, ...fallback].slice(0, 8)
  return pool.slice(0, 8).map((f, idx) => {
    const issue = [...(f.issues || [])].sort((a, b) => (SEV_RANK[a.severity] || 3) - (SEV_RANK[b.severity] || 3))[0]
    if (!issue) return null
    const sc = (issue.wcag || '').replace(/^SC_/, '').replace(/_/g, '.')
    const ba = ITEM_BA[sc] || { meta: 'review AI proposal', before: (d) => d || 'issue found' }
    // The demo's stand-in for hitl_queue.proposals. Present only for the criteria the model
    // drafts a value for; the rest either carry an applied remediation_diff (simRemediationDiffs,
    // once the demo has run remediation) or are a judgement call with nothing to show. No card
    // gets a canned "AI fix applied" string — see WhyReview.
    const proposals = simProposalsFor(sc, f.file)
    const p = proposals?.[0]
    return {
      id: idx + 1,
      icon: ITEM_ICON[sc] || '◈',
      title: `${(f.file.split('.').pop() || 'DOC').toUpperCase()} · ${issue.detail || ITEM_NAME[sc] || sc}`,
      meta: ba.meta,
      file: f.file,
      ruleId: sc,
      // buildEvidenceCard reads the hitl_queue column name, `rule_id`. The SIM item carried only
      // the camelCase `ruleId`, so every demo card fell back to card.wcag = '—' and showed no
      // criterion at all — the one number a reviewer needs to know what they are being asked.
      rule_id: sc,
      aiDraftable: AI_DRAFTABLE_SCS.has(sc),
      source: f.sourceName,
      rule: `WCAG ${sc}${ITEM_NAME[sc] ? ' — ' + ITEM_NAME[sc] : ''}`,
      before: ba.before(issue.detail, f),
      after: p?.proposed_value ?? null,
      proposals,
      thumb: p?.thumb ?? null,
      rationale: p?.rationale ?? null,
      proposalSource: p?.source ?? null,
      hasProposal: !!p,
    }
  }).filter(Boolean)
}

// Per-card automation badge (§4) — we retired the permanent 🟢🟡🔴 legend; the badge now
// lives ON each card so its meaning is local, never a floating key you have to remember.
const AUTO_BADGE = {
  auto:   { cls: 'ab-auto',   label: '🟢 Auto Applied' },
  review: { cls: 'ab-review', label: '🟡 Review Suggested' },
  human:  { cls: 'ab-human',  label: '🔴 Human Required' },
}
function AutoBadge({ kind }) {
  const b = AUTO_BADGE[kind] || AUTO_BADGE.review
  return <span className={`autobadge ${b.cls}`}>{b.label}</span>
}

// GitHub-style progress rail (§2) — where am I in Scan → Assess → Remediate → AI Work Inbox
// → Verify → Publish. `state` is 'done' | 'active' | 'pending'; an active step may carry a
// count (the human-review backlog).
function ProgressRail({ steps }) {
  return (
    <nav className="progressrail" aria-label="Remediation progress">
      {steps.map((s, i) => (
        <div key={s.key} className={`prstep pr-${s.state}`}>
          <span className="prmark" aria-hidden="true">{s.state === 'done' ? '✓' : s.state === 'active' ? '●' : '○'}</span>
          <span className="prlabel">{s.label}</span>
          {s.count != null && s.count > 0 && <span className="prcount">{s.count}</span>}
          {i < steps.length - 1 && <span className="prsep" aria-hidden="true">›</span>}
        </div>
      ))}
    </nav>
  )
}

// The current→remediated comparison, so a reviewer approves against evidence rather than a
// promise. `applied` distinguishes a fix already written into the document (remediation_diff,
// verified-cleared) from an AI draft that this very approval would accept — the reviewer must
// never confuse "this is what the file says now" with "this is what the model would like it
// to say". Both halves are real values; there is no template branch.
export function ReviewComparison({ comparison }) {
  const { before, after, applied } = comparison
  return (
    <div className="whyreview-ba" aria-label={applied ? 'Before and after the applied fix' : 'Current value and the AI draft'}>
      <div className="diffbox before">
        <span className="difftag">{applied ? 'before' : 'current'}</span>
        <code>{before || '— nothing (the value is absent)'}</code>
      </div>
      <div className="diffbox after">
        <span className="difftag">{applied ? 'after · applied to the document' : 'AI draft · not applied until you approve'}</span>
        <code>{after}</code>
      </div>
    </div>
  )
}

// "Why am I reviewing this?" (§3) — the honest evidence a compliance officer needs to act:
// the confidence.js level + its concrete basis (never a fabricated %), the plain-language
// escalation reason, the page the finding sits on, and — the point of the panel — what the
// document says now versus what it would say once remediated.
function WhyReview({ sc, suggested, before, beforeLiteral, comparison, thumb, thumbKind,
                    rationale, proposalSource, hasProposal, file, scanId, page }) {
  const conf = confidenceForFinding({ sc })
  const reason = metaFor({ rule_id: sc }).reason
  return (
    <div className="whyreview">
      <div className="whyreview-hd">Why am I reviewing this?</div>
      <div className="whyreview-body" style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        {/* What the reviewer must judge. Two sources, in order of specificity:
            1. the proposal's own image — the embedded picture, or a reading-order page render;
            2. failing that, the rendered PAGE the finding sits on.
            (2) is what the AI Work Inbox has always shown and this card never did: a text
            finding (3.1.2 language, 2.4.4 link text) carries no image, so ProposalThumb drew
            nothing and the reviewer was asked to approve a change to a passage they could not
            see. `page` comes from hitl_queue.page — the analysers' own attribution, absent
            when they could not attribute one, never defaulted to the cover.
            A PPTX renders neither: api/render.py is PDF-only, so a deck shows nothing here
            rather than a picture of the wrong document. */}
        {thumb
          ? <ProposalThumb thumb={thumb} alt={thumbAlt(thumbKind, file)} size={thumbSize(thumbKind)} />
          : (scanId && file && <Thumbnail scanId={scanId} file={file} page={page || 1}
                                          className="whyreview-thumb" maxHeight={150} />)}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="whyreview-row">
            <span className="muted">Trust signal</span>
            <span className={confClass(conf.level)} title={`tier: ${conf.level.label}`}>{conf.basis}</span>
          </div>
          <div className="whyreview-row"><span className="muted">Reason</span><span>{reason}</span></div>
          {/* Where to look. Only stated when the analysers attributed a page — a reviewer sent to
              "page 1" for a finding on page 7 checks the wrong thing and approves blind. */}
          {/* A deck has slides, not pages — pageNoun keeps the card honest about the format. */}
          {page && <div className="whyreview-row"><span className="muted">Found on</span><span>{pageNoun(file)} {page}</span></div>}
          {/* What the document says now versus what it would say once remediated. Both halves are
              real values — a remediation_diff row, or the proposal's own literal `before` and
              drafted value — so this renders only when such a pair exists. */}
          {comparison ? <ReviewComparison comparison={comparison} /> : (
            <>
              {/* No comparison. Show the offending passage ONLY when the proposal carried a
                  literal one: `ba.before()` is a description of the defect ("image / chart — no
                  alt text"), not a value, and labelling that "current text" would put a sentence
                  the document does not contain in front of a reviewer. When it is absent the
                  page render above, not a sentence, is what they judge. */}
              {beforeLiteral && before && (
                <div className="whyreview-row">
                  <span className="muted">Current text</span>
                  <span className="whyreview-before">{before}</span>
                </div>
              )}
              {/* Nothing was applied and no model drafted a value. Say so. This line used to
                  print a canned "AI-generated alt text added" on every card, claiming a fix
                  whether or not one had happened. */}
              <div className="whyreview-row">
                <span className="muted">{suggested && hasProposal ? 'AI suggested value' : 'Next step'}</span>
                <span className="whyreview-sugg">{suggested || noDraftHint(sc)}</span>
              </div>
            </>
          )}
          {rationale && (
            <div className="whyreview-row">
              <span className="muted">Why this draft</span>
              <span>{rationale}{proposalSource ? ` · ${proposalSource}` : ''}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// One human-review card. Dominant surface (§3): the card leads with WHAT and WHY, carries
// its own badge (§4), and exposes the review actions inline — no competing top-level buttons.
function ReviewItemCard({ item, scanDiffs = [], onOpen, onApprove, onSelf, onReject, disabled }) {
  const sc = scOf(item.ruleId || item.rule || item.title)
  const conf = confidenceForFinding({ sc })
  const badgeKind = conf.level.rank <= 1 ? 'human' : 'review'   // Low → human required, else review suggested
  // Derived here, not at fetch time: the remediation_diff rows load in parallel with the queue,
  // so an item mapped before they land would hold an empty comparison forever.
  const comparison = comparisonFor(item, scanDiffs)
  // More images than this card can show. Its Approve must not stand in for all of them.
  const multiImage = (item.proposals?.length || 0) > 1
  return (
    <div className="reviewcard">
      <div className="reviewcard-top">
        <span className="qico" aria-hidden="true">{item.icon}</span>
        <div className="reviewcard-title">
          <button className="remname" onClick={onOpen}>{item.title}</button>
          <div className="qmeta">{item.file} · {item.rule}</div>
        </div>
        <AutoBadge kind={badgeKind} />
      </div>
      <WhyReview sc={sc} suggested={item.after} before={item.before} beforeLiteral={item.beforeLiteral}
                 comparison={comparison}
                 thumb={item.thumb} thumbKind={item.thumbKind} rationale={item.rationale}
                 proposalSource={item.proposalSource} hasProposal={item.hasProposal} file={item.file}
                 scanId={item.scanId} page={item.page} />
      <div className="reviewcard-actions">
        {/* This card shows ONE image. Approving from here would accept a description for every
            other image in the file that the reviewer never saw — and the server now writes
            those descriptions into the document. Send them to the drawer, which shows each
            image beside its own text. */}
        {multiImage
          ? <button className="qbtn approve" disabled={disabled} onClick={onOpen}
                    title="Each image needs its own description — review them side by side">
              Review {item.proposals.length} images →
            </button>
          : <button className="qbtn approve" disabled={disabled} onClick={onApprove}>✓ Approve</button>}
        <button className="qbtn self" disabled={disabled} onClick={onSelf} title="Take ownership — fix it yourself, then re-scan to confirm">✋ I’ll fix it</button>
        <button className="qbtn reject" disabled={disabled} onClick={onReject}>✕ Reject</button>
      </div>
    </div>
  )
}

// Recent AI fixes — a GROUPED summary (§6), not a repetitive per-row list. One chip per
// rule ("Added 14 image descriptions"), an "Accessibility improvements" impact row (§7),
// and "View details" expands to the real applied values + thumbnails (applied_fixes).
// Everything is a straight count of what was written.
function GroupedFixes({ fixGroups, appliedFixes = [], impact }) {
  const [showDetail, setShowDetail] = useState(false)
  if (!fixGroups.length) return null
  return (
    <section className="panel">
      <div className="fixhd">
        <h2 style={{ margin: 0 }}>Recent AI fixes <span className="muted" style={{ fontSize: 13, fontWeight: 400 }}>· what was corrected automatically</span></h2>
      </div>
      <div className="fixgroups">
        {fixGroups.map((g) => <span className="fixgroup" key={g.sc}><span aria-hidden="true">✓</span> {g.phrase}</span>)}
        {appliedFixes.length > 0 && (
          <button className="linkbtn" onClick={() => setShowDetail((v) => !v)}>{showDetail ? 'Hide details' : 'View details →'}</button>
        )}
      </div>
      {impact && impact.length > 0 && (
        <div className="impactrow" aria-label="Accessibility improvements by category">
          <span className="impacthd muted">Accessibility improvements</span>
          {impact.map((c) => (
            <span className="impacttile" key={c.category}><b>{c.count}</b> <span className="muted">{c.category}</span></span>
          ))}
        </div>
      )}
      {showDetail && appliedFixes.length > 0 && (
        <div className="recentfixes" style={{ marginTop: 12 }}>
          {appliedFixes.slice(0, 12).map((a, i) => {
            const sc = scOf(a.rule_id)
            return (
              <details className="recentfix" key={i}>
                <summary>
                  {/* Through ProposalThumb, not a raw <img>: it is the one place that checks a
                      thumb is really a base64 image data-URL before it reaches an `src`, and it
                      letterboxes rather than cover-cropping — a PDF's thumb is a whole rendered
                      page, which a cover-crop would reduce to a slice of margin. */}
                  <ProposalThumb thumb={a.thumb} size={36} alt={appliedFixAlt(a.file)}
                                 className="recentfix-thumb" />
                  <span className="fmtchip">{((a.file || '').split('.').pop() || 'DOC').toUpperCase()}</span>
                  <span className="muted" style={{ fontSize: 12 }}>WCAG {sc} · {ITEM_NAME[sc] || 'non-text content'} · {a.file}</span>
                  <span className="fixauto" style={{ marginLeft: 'auto', fontSize: 12 }}>⚡ auto-applied</span>
                </summary>
                <div className="diffbox after"><span className="difftag">applied</span>{a.value}{a.source ? <span className="muted" style={{ fontSize: 11, marginLeft: 6 }}>· {a.source}</span> : null}</div>
              </details>
            )
          })}
        </div>
      )}
    </section>
  )
}

// Verification state (§8) — real, tied to the re-scan/job state; never "0 → 0".
function VerifyState({ state, pct, remaining, ready, latest }) {
  if (state === 'running') return (
    <div className="verify-run" role="status" aria-live="polite">
      <div className="verify-track"><i style={{ width: `${pct}%` }} /></div>
      <span>Running… <b>{pct}%</b>{latest ? <> · last verified <span className="fname">{latest}</span></> : null}</span>
    </div>
  )
  if (state === 'waiting') return (
    <div className="verify-wait" role="status">⏳ Waiting on approval · <b>{remaining}</b> item{remaining === 1 ? '' : 's'} remaining. Verification begins automatically once you approve.</div>
  )
  if (state === 'complete') return (
    <div className="okline verify-done">✓ Verification complete · <b>{ready}</b> document{ready === 1 ? '' : 's'} re-validated and ready to publish.</div>
  )
  return <div className="muted">Not started — approve the review items or run remediation and verification begins automatically.</div>
}

// readOnly: time-travel replay — historical scans are for looking, not enqueuing
// real remediation jobs against (decisions stay editable: per-scan decision saves
// are the time-travel feature itself).
export default function Remediate({ run, files = [], decisions = {}, setDecisions, triage = {}, setTriage, aiEnabled = true, readOnly = false, onRefresh, onHitlCount, onNavigate }) {
  const [queue, setQueue] = useState([])
  const [acted, setActed] = useState({ approved: 0, rejected: 0, deferred: 0 })
  const [deferredItems, setDeferredItems] = useState([])
  // Real applied-fix evidence: scan-wide before→after (all fix types, verified-cleared) +
  // the concrete AI-written values/thumbnails. Every hero/impact/recent-fix count is a
  // straight count of these rows — never a fabricated number (see fixSummary.js).
  const [scanDiffs, setScanDiffs] = useState([])
  const [appliedFixes, setAppliedFixes] = useState([])
  const runId = run?.id
  const fetchFixes = () => {
    if (!runId) { setScanDiffs([]); setAppliedFixes([]); return }
    Promise.all([getScanRemediationDiffs(runId), getAppliedFixes(runId)])
      .then(([d, a]) => { setScanDiffs(Array.isArray(d) ? d : []); setAppliedFixes(Array.isArray(a) ? a : []) })
      .catch(() => {})
  }
  useEffect(() => {
    setActed({ approved: 0, rejected: 0, deferred: 0 }); setDeferredItems([])
    clearInterval(pollRef.current); setRemProg(null); setRemBusy(false); setServerFixed(0); setRemMsg('')
    fetchFixes()
    if (!runId) { setQueue(SIM ? buildHumanQueue(files, {}) : []); return }
    if (SIM) { setQueue(buildHumanQueue(files, {})); return }
    autoPopulateHitlQueue(runId)
      .then(() => listHitlQueue(runId, 'pending'))
      .then((items) => setQueue((items || []).map((it) => ({ ...dbItemToUi(it, files), _raw: it }))))
      .catch(() => setQueue(buildHumanQueue(files, {})))
  }, [runId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Drain in sync with the unified inbox: when an item is approved/rejected in the popup
  // (or anywhere), re-fetch the pending set so "N remaining" + the review banner update,
  // and re-pull the applied-fix evidence so the counts move with real progress.
  useEffect(() => {
    if (!runId || SIM) return
    const reload = () => {
      listHitlQueue(runId, 'pending')
        .then((items) => setQueue((items || []).map((it) => ({ ...dbItemToUi(it, files), _raw: it })))).catch(() => {})
      fetchFixes()
    }
    window.addEventListener('acp:hitl-changed', reload)
    return () => window.removeEventListener('acp:hitl-changed', reload)
  }, [runId, files]) // eslint-disable-line react-hooks/exhaustive-deps

  // Derive fix-type breakdown from auto-action files in the corpus
  const fixTypesDisplay = useMemo(() => {
    const counts = {}
    files.filter((f) => f.rec?.action === 'auto').forEach((f) => (f.issues || []).forEach((i) => {
      const m = FIX_WCAG_LABELS[i.wcag]; if (m) counts[m.label] = (counts[m.label] || { value: 0, color: m.color, order: Object.keys(FIX_WCAG_LABELS).indexOf(i.wcag) })
      if (m) counts[m.label].value++
    }))
    // No fabricated fallback: an estate with zero auto-fixable files shows an
    // honest 0 and hides the breakdown, never invented counts.
    return Object.entries(counts).map(([label, { value, color }]) => ({ label, value, color })).sort((a, b) => b.value - a.value).slice(0, 5)
  }, [files])
  const autoFixed = fixTypesDisplay.reduce((a, f) => a + f.value, 0)
  const [selItem, setSelItem] = useState(null)
  const [self, setSelf] = useState([])
  const [sel, setSel] = useState(null)
  const [seg, setSeg] = useState(null)
  const [editing, setEditing] = useState(null)
  const [remBusy, setRemBusy] = useState(false)
  const [remMsg, setRemMsg] = useState('')
  const [remProg, setRemProg] = useState(null)   // { total, done, latest, failed }
  const [serverFixed, setServerFixed] = useState(0)  // files fixed server-side this scan (persists after each batch)
  const pollRef = useRef(null)
  const remStartRef = useRef(false)   // synchronous guard — remBusy is state, two clicks in one frame both read false
  useEffect(() => () => clearInterval(pollRef.current), [])
  const REMKEY = (id) => `acp-remed-${id || 'none'}`

  // One poll loop, shared by a fresh run and by resume-after-navigation. Ticks the live
  // counters every 1.5s off the worker queue; on drain it banks the fixed count + clears.
  const startPoll = (total) => {
    clearInterval(pollRef.current)
    let pollFails = 0
    pollRef.current = setInterval(async () => {
      try {
        const s = await getRemediationStatus(runId)
        pollFails = 0
        const done = Math.max(0, total - (s.in_flight || 0))
        setRemProg({ total, done, latest: s.latest_file, failed: s.failed || 0 })
        if (!s.in_flight) {                         // queue drained — batch complete
          clearInterval(pollRef.current)
          setRemProg(null); setRemBusy(false)
          const ok = Math.max(0, total - (s.failed || 0))
          setServerFixed((n) => n + ok)             // bank the fixes so the KPI holds after
          setRemMsg(`✓ Remediation complete — ${ok} document${ok === 1 ? '' : 's'} fixed${s.failed ? `, ${s.failed} failed` : ''}.`)
          try { sessionStorage.removeItem(REMKEY(runId)) } catch { /* ignore */ }
          onRefresh?.()                             // refresh scan so the write-back banner updates
          fetchFixes()                              // re-pull the applied-fix evidence → hero/impact counts move
          // Re-list the HITL queue: the just-finished jobs route every finding they could
          // NOT verifiably auto-clear (contrast sign-off, link purpose, …) to human review
          // server-side. Without this re-fetch the queue stays on its mount-time snapshot,
          // so those new review items never surface and the reviewer has nothing to approve.
          if (!SIM) listHitlQueue(runId, 'pending')
            .then((items) => setQueue((items || []).map((it) => dbItemToUi(it, files))))
            .catch(() => {})
        }
      } catch {
        // Transient errors retry, but not forever: ~30s of consecutive misses means
        // the API is unreachable — stop and say so instead of spinning silently.
        // The sessionStorage denominator survives, so a reload resumes watching.
        if (++pollFails >= 20) {
          clearInterval(pollRef.current)
          setRemBusy(false); setRemProg(null)
          setRemMsg('Lost contact with the job queue — the batch may still be running server-side. Reload to resume watching.')
        }
      }
    }, 1500)
  }

  // Resume the live view across tab switches / reloads: the poll lives in this component, so
  // without this, navigating away mid-run and back would freeze the cards. The denominator is
  // restored from sessionStorage (written when the run starts).
  useEffect(() => {
    if (!runId) return
    let saved = null
    try { saved = JSON.parse(sessionStorage.getItem(REMKEY(runId)) || 'null') } catch { /* ignore */ }
    if (saved?.total) { setRemBusy(true); setRemProg({ total: saved.total, done: 0, latest: null, failed: 0 }); startPoll(saved.total) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])
  // SIM: rebuild queue when triage changes (real mode: queue is DB-driven, unaffected by triage).
  useEffect(() => {
    if (SIM) setQueue(buildHumanQueue(files, triage))
  }, [triage]) // eslint-disable-line react-hooks/exhaustive-deps

  const runServerRemediation = async (scopeFiles) => {
    if (!runId || remBusy || remStartRef.current) return
    // Say why nothing will happen, BEFORE the round trip. The old path posted an empty scope,
    // the server answered enqueued:0, and the UI said "no eligible files with issues" — true,
    // useless, and indistinguishable from a button that did nothing at all.
    if (!scopeFiles || scopeFiles.length === 0) {
      setRemMsg(emptyScopeReason(files, scopeOpts))
      return
    }
    remStartRef.current = true
    setRemBusy(true); setRemMsg(''); setRemProg(null)
    const scope = scopeFiles?.map((f) => f.file)
    try {
      const r = await remediateScan(runId, scope)
      if (!r.enqueued) {
        // We sent a non-empty scope and the server enqueued nothing: the client's view of
        // eligibility is stale (another session remediated them, or the scan moved on). Say
        // that, rather than repeating the empty-scope line and implying the user chose wrong.
        setRemMsg(`Nothing to remediate — the server found no eligible work in the ${scope.length} `
                  + `document${scope.length === 1 ? '' : 's'} sent. They may already have been `
                  + `remediated elsewhere; re-scan to refresh.`)
        setRemBusy(false); return
      }
      // In-process pool OR the standalone worker container's heartbeat (#113) counts as manned.
      if (!r.workers && !r.worker_tier_alive) { setRemMsg(`Enqueued ${r.enqueued}, but no workers are available — the worker service looks down; check Monitor.`); setRemBusy(false); return }
      const total = r.enqueued
      setRemProg({ total, done: 0, latest: null, failed: 0 })
      try { sessionStorage.setItem(REMKEY(runId), JSON.stringify({ total })) } catch { /* ignore */ }
      startPoll(total)
    } catch (e) {
      setRemMsg(`Could not enqueue: ${e.message || e}`); setRemBusy(false)
    } finally {
      remStartRef.current = false
    }
  }
  const triageFile = (file, st) => setTriage((t) => { const n = { ...t }; if (st == null) delete n[file]; else n[file] = st; return n })
  const revalidated = files.filter((f) => f.compliant)

  // A review decision that fails to reach the server must NOT look like one that succeeded.
  // The optimistic update pulls the card out of the queue and bumps the counter before the
  // write; every write used to end in `.catch(() => {})`, so a 401 or a 500 left the reviewer
  // believing they had signed something off that the server never recorded. In a compliance
  // product an unrecorded approval is worse than a visible failure. Put the card back, undo
  // the count, and say so.
  const undoAct = (item, kind, err) => {
    if (item) {
      setQueue((q) => (q.some((x) => x.id === item.id) ? q : [item, ...q]))
      if (kind === 'deferred') setDeferredItems((d) => d.filter((x) => x.id !== item.id))
    }
    setActed((a) => ({ ...a, [kind]: Math.max(0, (a[kind] || 0) - 1) }))
    window.dispatchEvent(new Event('acp:hitl-changed'))
    setActError(`Your ${kind === 'deferred' ? 'skip' : kind} of “${item?.file || 'this finding'}” was NOT saved: `
                + `${err?.message || err}. It is back in the queue — try again.`)
  }

  const act = (id, kind, editedValue, approvedValues) => {
    const item = queue.find((x) => x.id === id)
    setActError(null)
    setQueue((q) => q.filter((x) => x.id !== id))
    setSelItem(null)
    if (kind === 'self') { if (item) setSelf((s) => [{ ...item, status: 'awaiting' }, ...s]); return }
    if (kind === 'deferred') {
      if (item) setDeferredItems((d) => [...d, item])
      setActed((a) => ({ ...a, deferred: a.deferred + 1 }))
      if (!SIM && item?.id) updateHitlItem(item.id, 'skipped').catch((e) => undoAct(item, 'deferred', e))
      return
    }
    setActed((a) => ({ ...a, [kind]: a[kind] + 1 }))
    window.dispatchEvent(new Event('acp:hitl-changed'))
    const apiStatus = kind === 'approved' ? 'approved' : kind === 'rejected' ? 'rejected' : null
    // approved_value is the headline text (audit log, telemetry); approvedValues carries one
    // final text per image, keyed by position to the row's proposals. The server writes those
    // into the document at each proposal's locator, re-scans the result, and only then lets
    // the file certify — so what is approved here is what the document ends up saying.
    if (!SIM && item?.id && apiStatus) {
      const p = updateHitlItem(item.id, apiStatus, null,
                               apiStatus === 'approved' ? (editedValue || null) : null,
                               { approvedValues: apiStatus === 'approved' ? (approvedValues || null) : null })
      // On approval the server re-validates the file: once its every review item is
      // approved it flips to compliant and enters the publish queue. Refresh the scan so
      // "Re-validated & ready to publish" (and the Publish tab) pick that up immediately.
      // Two-arg then, NOT .then().catch(): a chained catch would also see a rejection from
      // onRefresh() and roll back a decision the server had already accepted. The refresh is
      // cosmetic; only the write's own failure may undo the decision.
      p.then(
        () => {
          if (apiStatus !== 'approved') return
          try { const r = onRefresh?.(); if (r && typeof r.catch === 'function') r.catch(() => {}) }
          catch { /* the refresh is cosmetic — never let it disturb a saved decision */ }
        },
        (e) => undoAct(item, kind, e),
      )
    }
  }
  // Adapter for the unified EvidenceCard: it calls onAct(id, status, note, finalValue, telemetry);
  // map to this tab's act(id, kind, editedValue, approvedValues). EvidenceCard's "I'll fix it" sends
  // status='skipped' → this tab's self-fix lane. The per-image approved values ride in telemetry.
  const evAct = (id, status, _note, finalValue, tel) => {
    if (readOnly) return   // time-travel replay is look-only — never mutate a historical scan
    act(id, status === 'skipped' ? 'self' : status, finalValue, tel && tel.approvedValues)
  }

  const draftAi = (item) => suggestFix(item.scanId || runId, item.file, item.ruleId).then((r) => r?.suggestion)
  const rescan = (id) => {
    const item = self.find((x) => x.id === id)
    setSelf((s) => s.map((x) => x.id === id ? { ...x, status: 'scanning' } : x))
    if (SIM || !runId || !item?.file) {
      setTimeout(() => setSelf((s) => s.map((x) => x.id === id ? { ...x, status: 'verified' } : x)), 1700)
      return
    }
    rescoreFile(runId, item.file)
      .then(({ job_id }) => {
        if (!job_id) throw new Error('no job_id')
        const poll = setInterval(async () => {
          try {
            const j = await getJob(job_id)
            if (j?.status === 'done' || j?.status === 'error') {
              clearInterval(poll)
              setSelf((s) => s.map((x) => x.id === id ? { ...x, status: j.status === 'done' ? 'verified' : 'error' } : x))
              onRefresh?.()
            }
          } catch { clearInterval(poll); setSelf((s) => s.map((x) => x.id === id ? { ...x, status: 'verified' } : x)) }
        }, 1500)
      })
      .catch(() => setSelf((s) => s.map((x) => x.id === id ? { ...x, status: 'verified' } : x)))
  }
  const verified = self.filter((x) => x.status === 'verified').length
  // Live re-verified KPI = manual self-fixes + banked server fixes + the in-flight batch's
  // completions (ticks every poll), so the card moves in real time with the worker queue.
  const liveFixed = remProg ? Math.max(0, remProg.done - (remProg.failed || 0)) : 0
  const reVerified = verified + serverFixed + liveFixed
  const remLive = !!remProg || remBusy
  const pendingHitlFiles = new Set(queue.map((q) => q.file))
  const totalHitl = queue.length + acted.approved + acted.rejected + acted.deferred + self.length
  const hitlProgress = totalHitl > 0 ? Math.round(((totalHitl - queue.length) / totalHitl) * 100) : 0
  useEffect(() => { onHitlCount?.(queue.length) }, [queue.length, onHitlCount])
  // Don't surface remediation numbers until the user has actually started remediating
  // (ran "Remediate all" or acted on a review item) — pre-engagement estimates read as
  // in-progress work and confuse first-time users. Until then the cards show zeros.
  const remStarted = remProg != null || remBusy || serverFixed > 0 || (acted.approved + acted.rejected + acted.deferred + self.length) > 0

  // --- remediation plan + decisions (moved from Discover) ---
  const plan = files.length ? recommendationSummary(files) : null
  const planCards = plan ? plan.buckets.filter((b) => REM_ACTIONS.includes(b.action)) : []
  // Published business ontology takes precedence in the queue order (Critical → Low),
  // then the AI risk triage breaks ties.
  const ontRank = (f) => f.ont?.priority ? PRI_RANK[f.ont.priority] : 9
  const hasInscopeSelections = Object.values(triage).some((v) => v === 'inscope')
  // One eligibility test, shared with emptyScopeReason() — so what the button acts on and what
  // it says when it can't act on anything are derived from the same rules, in the same order.
  const scopeOpts = { triage, hasInscopeSelections, remActions: REM_ACTIONS }
  // Same eligibility test as `remediable` below, counted rather than filtered — so what the
  // panel SAYS it will skip and what the button actually skips cannot drift apart.
  const scopeInfo = scopeSummary(files, scopeOpts)
  const remediable = remediableFiles(files, scopeOpts)
    .sort((a, b) => (ontRank(a) - ontRank(b)) || (priority(b) - priority(a)))
  const ontCount = remediable.filter((f) => f.ont).length
  const autoFiles = remediable.filter((f) => {
    const eff = decisions[f.file]?.state === 'override' ? decisions[f.file].action : f.rec?.action
    return eff === 'auto' && !decisions[f.file]
  })
  const batchAutoRemediate = () => setDecisions?.((s) => { const n = { ...s }; autoFiles.forEach((f) => { n[f.file] = { state: 'accepted' } }); return n })
  const decide = (file, d) => { setDecisions?.((s) => ({ ...s, [file]: d })); setEditing(null) }
  const undo = (file) => setDecisions?.((s) => { const n = { ...s }; delete n[file]; return n })
  const acceptAll = () => setDecisions?.((s) => { const n = { ...s }; remediable.forEach((f) => { if (!n[f.file]) n[f.file] = { state: 'accepted' } }); return n })
  const dcount = (st) => remediable.filter((f) => decisions[f.file]?.state === st).length
  const pending = remediable.length - dcount('accepted') - dcount('override') - dcount('rejected')
  const humanCount = pending - autoFiles.length   // pending files NOT auto — the gap between the two plan buttons

  // business priority (findings-based)
  const flagged = files.filter((f) => (f.issues || []).length)
  const findingsBy = (keyFn, order) => {
    const m = {}; flagged.forEach((f) => { const k = keyFn(f); if (k != null) m[k] = (m[k] || 0) + f.issues.length })
    return (order ? order.filter((k) => m[k]).map((k) => [k, m[k]]) : Object.entries(m).sort((a, b) => b[1] - a[1]))
  }
  const deptData = findingsBy((f) => f.department).slice(0, 8).map(([label, value]) => ({ label, value, color: '#7a5c8e' }))
  const senData = findingsBy((f) => f.seniority, SENIORITY_ORDER).map(([label, value]) => ({ label, value, color: SR_COLOR[label] }))
  const expData = findingsBy(exposureOf, ['public-facing', 'high-traffic', 'internal']).map(([label, value]) => ({ label, value, color: EXP_COLOR[label] }))
  const pubCrit = flagged.filter((f) => (f.tags || []).includes('public-facing') && (f.issues || []).some((i) => i.severity === 'CRITICAL')).length
  const execFlagged = flagged.filter((f) => f.seniority === 'Executive').length
  const drill = (title, sub, pred) => setSeg({ title, subtitle: sub, files: flagged.filter(pred) })

  const _triageFiles = files.filter((f) => !(f.remediated_at || f.drive_write_url))
  const written = files.filter((f) => f.drive_write_url).length
  // Once remediation has run, an empty HITL queue means every fix went through the
  // automated path — approved/deferred (HITL decision counts) are meaningless there,
  // so swap them for the KPI that actually reflects what happened: writes to Drive.
  const pureAutomated = remStarted && totalHitl === 0

  // ── Reframed view (Review → Approve → Verify → Publish) ──────────────────────────
  // Every count below is a straight tally of real pipeline rows — applied-fix evidence,
  // the live HITL queue, the recommendation estimate — never a fabricated number.
  const fixSource = scanDiffs.length ? scanDiffs : appliedFixes   // diffs cover all fix types; applied_fixes is the fallback for older scans
  const fixGroups = groupFixesByRule(fixSource)
  const impact = summarizeImpact(fixSource)
  const fixedCount = totalFixes(fixSource)
  const fixesByFile = {}; fixSource.forEach((r) => { fixesByFile[r.file] = (fixesByFile[r.file] || 0) + 1 })
  const reviewByFile = {}; queue.forEach((q) => { reviewByFile[q.file] = (reviewByFile[q.file] || 0) + 1 })
  // Reviewer time, MEASURED (hitl_events.review_ms). Replaces "est. savings", which was one
  // invented constant (35 min/finding by hand) minus another (~1 min/finding automated).
  // A saving needs a counterfactual nobody ever timed; an average review time is a fact.
  // A review decision the server refused. Loud, and sticky until the next attempt.
  const [actError, setActError] = useState(null)
  const [reviewStats, setReviewStats] = useState(null)
  useEffect(() => {
    if (!runId || SIM) { setReviewStats(null); return }
    let live = true
    const pull = () => getHitlAnalytics(runId).then((a) => { if (live) setReviewStats(a) }).catch(() => {})
    pull()
    window.addEventListener('acp:hitl-changed', pull)
    return () => { live = false; window.removeEventListener('acp:hitl-changed', pull) }
  }, [runId])
  const measured = measuredReviewTime(reviewStats)

  // Verification state — tied to the real re-scan/job state (§8), never "0 → 0".
  const verifyPct = remProg ? Math.round((remProg.done / Math.max(1, remProg.total)) * 100) : 0
  const verifyState = remLive ? 'running'
    : queue.length > 0 ? 'waiting'
    : (revalidated.length > 0 || written > 0 || reVerified > 0) ? 'complete'
    : 'idle'

  // Business risk — one recommendation from real signals (§9): public / high-traffic
  // exposure tags × open critical findings. Never invented.
  const publicDocs = files.filter((f) => (f.tags || []).includes('public-facing'))
  const trafficDocs = files.filter((f) => (f.tags || []).includes('high-traffic'))
  const criticalOpen = files.reduce((n, f) => n + (f.issues || []).filter((i) => i.severity === 'CRITICAL').length, 0)
  const pubCritDocs = publicDocs.filter((f) => (f.issues || []).some((i) => i.severity === 'CRITICAL')).length
  const risk = publicDocs.length && pubCritDocs > 0
    ? { level: 'high', text: `Public-facing content · ${pubCritDocs} document${pubCritDocs === 1 ? '' : 's'} with critical findings · HIGH RISK under ADA / EAA` }
    : (publicDocs.length || trafficDocs.length) && criticalOpen > 0
    ? { level: 'med', text: `${publicDocs.length ? 'Public-facing' : 'High-traffic'} content · ${criticalOpen} critical finding${criticalOpen === 1 ? '' : 's'} open · MEDIUM RISK` }
    : criticalOpen > 0
    ? { level: 'med', text: `Internal content · ${criticalOpen} critical finding${criticalOpen === 1 ? '' : 's'} open · MEDIUM RISK` }
    : publicDocs.length
    ? { level: 'low', text: 'Public-facing content · no critical findings · overall risk LOW' }
    : { level: 'low', text: 'Internal content only · overall risk LOW' }

  // One primary action at a time (§11): review → run → verify → publish.
  // Remediation is offered whenever a document is ELIGIBLE for it — `remediable` already
  // excludes anything with a fixed copy. It used to be gated on `!remStarted`, and remStarted
  // is true as soon as `acted.approved + acted.rejected + acted.deferred > 0`. So clearing the
  // review queue — the step that unblocks remediation — was exactly what removed the button
  // that runs it. The two branches were mutually exclusive and nobody could reach the second.
  const remRunning = remBusy || (remProg != null && remProg.done < remProg.total)
  const primary = readOnly ? null
    : queue.length > 0 ? { label: `Review ${queue.length} Remaining Issue${queue.length === 1 ? '' : 's'} →`, onClick: () => window.dispatchEvent(new Event('acp:open-inbox')) }
    : remRunning ? { label: '⏳ Remediating…', disabled: true }
    : verifyState === 'running' ? { label: '⏳ Verifying…', disabled: true }
    : remediable.length > 0 ? { label: '⚡ Run Remediation →', onClick: () => runServerRemediation(remediable), disabled: !runId }
    : (verifyState === 'complete' || revalidated.length > 0) ? { label: 'Publish Certified Copy →', onClick: () => onNavigate?.('publish') }
    : null

  // Progress rail state (§2).
  const progressSteps = [
    { key: 'scan', label: 'Scan', state: 'done' },
    { key: 'assess', label: 'Assess', state: 'done' },
    { key: 'remediate', label: 'Remediate', state: (remStarted || fixedCount > 0) ? 'done' : 'active' },
    { key: 'review', label: 'AI Work Inbox', state: queue.length > 0 ? 'active' : 'done', count: queue.length },
    { key: 'verify', label: 'Verify', state: verifyState === 'complete' ? 'done' : verifyState === 'running' ? 'active' : 'pending' },
    { key: 'publish', label: 'Publish', state: written > 0 ? 'done' : 'pending' },
  ]

  // Documents list (§5): triage + plan merged — one row per doc. Not-yet-fixed first, then
  // business priority. Triage counts drive the summary chips.
  const inscopeCount = _triageFiles.filter((f) => triage[f.file] === 'inscope').length
  const naCount = _triageFiles.filter((f) => triage[f.file] === 'na').length
  const deferCount = _triageFiles.filter((f) => triage[f.file] === 'defer').length
  const docList = [...files].sort((a, b) => {
    const aR = !!(a.remediated_at || a.drive_write_url), bR = !!(b.remediated_at || b.drive_write_url)
    if (aR !== bR) return aR ? 1 : -1
    return (ontRank(a) - ontRank(b)) || (priority(b) - priority(a))
  })
  const written2 = files.filter((f) => f.drive_write_url)
  const downloadOnly = files.filter((f) => f.remediated_at && !f.drive_write_url)

  return (
    <>
      {/* GitHub-style progress rail (§2) — where am I in the pipeline. */}
      <ProgressRail steps={progressSteps} />

      {/* HERO (§1) — the 5-second story + ONE primary action (§11). Every count is real:
          documents from the scan, issues fixed from applied-fix evidence, review from the
          live HITL queue, savings from the recommendation model. */}
      <section className="rem-hero">
        <div className="rem-hero-main">
          <h2 className="rem-hero-title">Accessibility remediation</h2>
          <div className="rem-hero-line">
            <b>{files.length}</b> document{files.length === 1 ? '' : 's'} processed
            {fixedCount > 0 && <> · <b className="rh-fixed">{fixedCount}</b> issue{fixedCount === 1 ? '' : 's'} fixed automatically</>}
            {queue.length > 0 && <> · <b className="rh-review">{queue.length}</b> need your review</>}
            {measured && (
              <span title={REVIEW_TIME_BASIS}> · avg review <b className="rh-review">{measured.avg}</b>
                <span className="muted"> over {measured.reviewed} decision{measured.reviewed === 1 ? '' : 's'}</span>
              </span>
            )}
          </div>
          {files.length > 0 && (
            <div className={`rem-risk risk-${risk.level}`}><b>Business risk:</b> {risk.text}</div>
          )}
        </div>
        {primary
          ? <button className="rem-hero-cta" disabled={primary.disabled} onClick={primary.onClick}>{primary.label}</button>
          : remStarted ? <span className="rh-done">All caught up ✓</span> : null}
      </section>

      {/* ── HUMAN REVIEW (§3) — the only section that needs interaction, so it dominates,
          directly under the hero. Each card carries its own badge (§4) and a
          "Why am I reviewing this?" panel (real confidence + reason + suggested value). ── */}
      <section className="panel rem-review-panel" id="rem-review">
        <div className="rem-sec-hd">
          <h2 style={{ margin: 0 }}>AI Work Inbox {queue.length > 0 ? <span className="reviewpill">{queue.length}</span> : <span className="muted">· all clear</span>}</h2>
          {totalHitl > 0 && (
            <div className="rem-sec-prog">
              <div className="conftrack" style={{ width: 120 }}><i style={{ width: `${hitlProgress}%`, background: hitlProgress === 100 ? '#3B6D11' : '#1F5FA8' }} /></div>
              <span className="muted">{totalHitl - queue.length} of {totalHitl} reviewed</span>
            </div>
          )}
          {/* Reviewer analytics (vision #39) — real counts from hitl_events, not a fabricated score:
              approval rate, how often the reviewer edited the AI draft (the calibration signal), and
              the average review time already computed by measuredReviewTime. */}
          {reviewStats && reviewStats.reviewed > 0 && (
            <div className="rev-analytics" style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 12, marginTop: 6, color: 'var(--muted)' }}>
              {reviewStats.approval_rate != null && (
                <span>Approval rate <b style={{ color: 'var(--ink)' }}>{Math.round(reviewStats.approval_rate * 100)}%</b></span>
              )}
              {reviewStats.edit_rate != null && (
                <span title="how often a reviewer edited the AI draft before approving — a calibration signal, not a confidence score">
                  AI draft edited <b style={{ color: 'var(--ink)' }}>{Math.round(reviewStats.edit_rate * 100)}%</b>
                </span>
              )}
              {measured && <span>Avg review <b style={{ color: 'var(--ink)' }}>{measured.avg}</b></span>}
            </div>
          )}
          {/* AI Quality (feedback intelligence): which rules are weakest + WHY rejections happen —
              real reviewer-decision counts, weakest-first, never a fabricated score. Renders only
              once there is signal (a rejection, or 3+ reviewed on some rule). */}
          {reviewStats && ((reviewStats.by_rule || []).some((r) => r.rejected > 0 || r.reviewed >= 3)) && (
            <div className="rev-quality" style={{ marginTop: 8, fontSize: 12, color: 'var(--muted)' }}>
              <span style={{ fontWeight: 700, color: 'var(--ink)' }}>AI quality · weakest rules first:</span>{' '}
              {(reviewStats.by_rule || []).filter((r) => r.reviewed > 0).slice(0, 4).map((r, i) => (
                <span key={r.key} title={Object.entries(r.reject_reasons || {}).map(([k, n]) => `${k.replace(/_/g, ' ')}: ${n}`).join(' · ') || 'no rejections'}>
                  {i > 0 && ' · '}
                  <b style={{ color: r.rejected > 0 ? '#A32D2D' : 'var(--ink)' }}>{r.key}</b>
                  {' '}{r.approved}✓{r.rejected > 0 && <span style={{ color: '#A32D2D' }}> {r.rejected}✕</span>}
                </span>
              ))}
              {Object.keys(reviewStats.reject_reasons || {}).length > 0 && (
                <span> — top reject reasons: {Object.entries(reviewStats.reject_reasons)
                  .sort((a, b) => b[1] - a[1]).slice(0, 3)
                  .map(([k, n]) => `${k.replace(/_/g, ' ')} (${n})`).join(', ')}</span>
              )}
            </div>
          )}
        </div>
        {/* A decision the server refused. It rolled back, so the card is in the queue again —
            say so loudly, because a reviewer who thinks they signed something off and did not
            is the worst outcome this screen can produce. */}
        {actError && (
          <p role="alert" className="rem-act-error"
             style={{ margin: '0 0 12px', padding: '10px 12px', borderRadius: 8, fontSize: 13,
                      background: '#FDECEC', color: '#8A1F1F', border: '1px solid #E9A8A8' }}>
            {actError}
          </p>
        )}
        {queue.length === 0 ? (
          <p className="muted">{totalHitl === 0
            ? 'Nothing needs your review — every fix was applied automatically. Items needing an AI-assisted fix or human sign-off will appear here.'
            : `All reviewed — ${acted.approved} approved, ${acted.rejected} rejected${acted.deferred ? `, ${acted.deferred} deferred` : ''}. Verification runs on the approved fixes.`}</p>
        ) : (
          <div className="reviewlist">
            {/* Unified review card (canonical vision #1): the SAME rich EvidenceCard the AI Work
                Inbox uses — pipeline ladder, ✨ Explain, Grounding/Validation trust states, provenance
                badge, grouped evidence, cert preview, native verify steps — now renders here too,
                fed the raw hitl_queue row. `q._raw` is the untransformed row (live); SIM falls back
                to the UI item. */}
            {queue.map((q) => (
              <EvidenceCard key={q.id} item={q._raw || q} onAct={evAct}
                traceUrl={q._raw?.scan_id ? openTraceUrl(q._raw.scan_id, 'file', q._raw.file) : null} />
            ))}
          </div>
        )}
      </section>

      {/* ── VERIFICATION (§8) — real state, tied to the re-scan/job, auto-begins on approval. ── */}
      <section className="panel" id="rem-verify">
        <div className="rem-sec-hd"><h2 style={{ margin: 0 }}>Verification</h2></div>
        <VerifyState state={verifyState} pct={verifyPct} remaining={queue.length} ready={revalidated.length} latest={remProg?.latest} />
        {revalidated.length > 0 && (
          <div className="publist" style={{ marginTop: 12 }}>
            {revalidated.slice(0, 12).map((f) => (
              <div className="pubrow" key={f.file}>
                <button className="remname" onClick={() => setSel(f)}>{f.file}<span className="muted"> · {f.sourceName}</span></button>
                <span className="okline" style={{ fontSize: 13 }}>✓ verified {f.score} / 100</span>
              </div>
            ))}
            {revalidated.length > 12 && <div className="muted" style={{ fontSize: 12, padding: '6px 2px' }}>+{revalidated.length - 12} more</div>}
          </div>
        )}
      </section>

      {/* ── DOCUMENTS (§5) — file triage + remediation plan merged into ONE list: per-doc
          progress · fixes · items needing you · scope · Open. Everything about a doc here. ── */}
      <section className="panel" id="rem-docs">
        <div className="rem-sec-hd">
          <h2 style={{ margin: 0 }}>Documents <span className="muted">· {docList.length}</span></h2>
          <div className="triagesum">
            <span className="trstatchip inscope">{inscopeCount} in scope</span>
            <span className="trstatchip na">{naCount} N/A</span>
            <span className="trstatchip defer">{deferCount} deferred</span>
            {/* The chips above count only EXPLICIT decisions. When an in-scope selection exists it
                also excludes every unmarked document, so without this chip the panel reported
                "2 in scope" beside 258 listed rows and said nothing about the 256 being dropped. */}
            {scopeInfo.restrictedBySelection && (
              <span className="trstatchip out" title="Marking any document ✓ restricts the run to marked documents only. These are not marked, so Remediate all will skip them.">
                {scopeInfo.excluded.outOfScope.toLocaleString()} excluded — not marked ✓
              </span>
            )}
          </div>
        </div>
        <p className="muted" style={{ fontSize: 12, margin: '0 0 10px' }}>
          Everything about each document in one place — progress, fixes applied, items needing you, and whether it’s in scope.
          Set scope per row: <b style={{ color: '#3B6D11' }}>✓</b> in scope · <b>N/A</b> skip · <b style={{ color: '#1F5FA8' }}>⏸</b> defer.
          {scopeInfo.restrictedBySelection
            ? <> <b style={{ color: '#8A2A20' }}>Because you marked {inscopeCount.toLocaleString()} document{inscopeCount === 1 ? '' : 's'} ✓, remediation runs on those alone</b> — the other {scopeInfo.excluded.outOfScope.toLocaleString()} are excluded until you mark them or clear the selection.</>
            : <> No document is marked ✓, so remediation runs on <b>all eligible documents</b>. Marking even one ✓ restricts the run to marked documents only.</>}
        </p>
        <div className="doclist">
          <div className="docrow dochead">
            <span>Document</span><span>Progress</span><span style={{ textAlign: 'center' }}>Fixes</span><span style={{ textAlign: 'center' }}>Review</span><span>Scope</span><span />
          </div>
          {docList.map((f) => {
            const done = !!(f.remediated_at || f.drive_write_url)
            const pct = done ? 100 : (f.score != null ? f.score : 0)
            const dec = triage[f.file]
            const nFix = fixesByFile[f.file] || 0
            const nRev = reviewByFile[f.file] || 0
            // Excluded BY THE SCOPE SELECTION specifically — not merely "unmarked". A document
            // with no automatic fix is already ineligible for its own reason and marking it ✓
            // would not change that, so calling it "excluded by your selection" would be the
            // same false precision this panel is being fixed for.
            const outOfScope = ineligibleReason(f, scopeOpts) === 'outOfScope'
            return (
              <div className={outOfScope ? 'docrow outofscope' : 'docrow'} key={f.file}>
                <div className="doccell-name">
                  <button className="remname" onClick={() => setSel(f)}>{f.file}</button>
                  <div className="docsub muted">
                    {f.sourceName}{f.department ? ` · ${f.department}` : ''}
                    {/* Said on the row itself, because three untouched buttons in the Scope cell
                        read as "not decided yet" — which is how 256 dropped documents looked
                        identical to 256 pending ones. */}
                    {outOfScope && <span className="docexcl"> · excluded — not marked ✓</span>}
                  </div>
                </div>
                <div className="docprog">
                  <div className="docbar"><i style={{ width: `${pct}%`, background: pct >= 90 ? '#3B6D11' : pct >= 60 ? '#BF8C00' : '#B43A2A' }} /></div>
                  <span className="docpct">{done ? '✓ certified' : `${pct}%`}</span>
                </div>
                <span className="doccount">{nFix > 0 ? <b style={{ color: '#3B6D11' }}>{nFix}</b> : <span className="muted">—</span>}</span>
                <span className="doccount">{nRev > 0 ? <b style={{ color: '#854F0B' }}>{nRev}</b> : <span className="muted">—</span>}</span>
                <span className="docscope">
                  {done ? <span className="trstatchip inscope">done</span>
                  : dec ? <><span className={`trstatchip ${dec}`}>{dec === 'inscope' ? '✓ in scope' : dec === 'na' ? 'N/A' : '⏸ deferred'}</span><button className="ghost small" onClick={() => triageFile(f.file, null)} title="Undo">↺</button></>
                  : <span className="scopebtns">
                      <button className="trbtn inscope" onClick={() => triageFile(f.file, 'inscope')} title={outOfScope ? 'Excluded — mark ✓ to include this document in remediation' : 'In scope — include in remediation'}>✓</button>
                      <button className="trbtn na" onClick={() => triageFile(f.file, 'na')} title="Not applicable — skip">N/A</button>
                      <button className="trbtn defer" onClick={() => triageFile(f.file, 'defer')} title="Defer — decide later">⏸</button>
                    </span>}
                </span>
                <button className="ghost small docopen" onClick={() => setSel(f)}>Open →</button>
              </div>
            )
          })}
        </div>
      </section>

      {/* ── Recent AI fixes, grouped (§6) + Accessibility improvements impact (§7) ── */}
      <GroupedFixes fixGroups={fixGroups} appliedFixes={appliedFixes} impact={impact} />

      {/* Self-remediation — you're fixing these yourself; visible whenever active. */}
      {self.length > 0 && (
        <section className="panel">
          <h2>Self-remediation <span className="muted">· you’re fixing these — re-scan to confirm</span></h2>
          <div className="queue">
            {self.map((it) => (
              <div className={`qrow${it.status === 'verified' ? ' qdone' : ''}`} key={it.id}>
                <span className="qico" aria-hidden="true">{it.icon}</span>
                <div className="qmain">
                  <div className="qtitle">{it.title} <span className="muted" style={{ fontSize: 12 }}>· {it.file}</span></div>
                  <div className="qmeta">{it.rule}</div>
                  <div className="selfstatus">
                    {it.status === 'awaiting' && <>
                      <span className="muted">awaiting your fix — open the file, apply it in the source, then confirm</span>
                      {SOURCE_URL[it.source] && <a className="ghost small" style={{ marginLeft: 8 }} href={SOURCE_URL[it.source]} target="_blank" rel="noopener noreferrer">↗ Open the file</a>}
                    </>}
                    {it.status === 'scanning' && <span className="muted"><span className="spinner" /> re-scanning across all engines…</span>}
                    {it.status === 'verified' && <span className="okline">✓ verified — finding cleared, now passing 100 / 100</span>}
                  </div>
                </div>
                {it.status === 'verified'
                  ? <span className="qbtn verified">✓ confirmed</span>
                  : <button className="qbtn rescan" disabled={it.status === 'scanning'} onClick={() => rescan(it.id)}>↻ Re-scan to confirm</button>}
              </div>
            ))}
          </div>
          <p className="muted" style={{ marginTop: 12 }}>When you remediate a document yourself, the agent re-runs every engine to independently confirm the fix before it’s certified — no manual sign-off taken on trust.</p>
        </section>
      )}

      {deferredItems.length > 0 && (
        <section className="panel">
          <h2>Deferred <span className="muted">· {deferredItems.length} item{deferredItems.length !== 1 && "s"} &mdash; resurface on next scan</span></h2>
          <div className="queue">
            {deferredItems.map((it) => (
              <div className="qrow" key={it.id} style={{ opacity: 0.7 }}>
                <span className="qico" aria-hidden="true">{it.icon}</span>
                <div className="qmain">
                  <div className="qtitle">{it.title} <span className="muted" style={{ fontSize: 12 }}>· {it.file}</span></div>
                  <div className="qmeta">{it.rule}</div>
                </div>
                <span className="trstatchip defer" style={{ fontSize: 12, padding: "3px 10px" }}>⏸ deferred</span>
                <button className="ghost small" onClick={() => { setDeferredItems((d) => d.filter((x) => x.id !== it.id)); setQueue((q) => [...q, it]); setActed((a) => ({ ...a, deferred: a.deferred - 1 })) }}>↺ restore</button>
              </div>
            ))}
          </div>
          <p className="muted" style={{ marginTop: 10 }}>Deferred findings are tracked in the compliance record and flagged automatically when the next scheduled scan runs.</p>
        </section>
      )}

      {/* ── ADVANCED (§10) — the engine, hidden by default: live metrics, worker queue,
          the remediation plan + accept/reject decisions, business-risk graphs, the
          server-side remediation runner, and the fixed-copy write-back. For architects /
          support; the default view above is the four-decision flow. ── */}
      <details className="rem-advanced rem-adv-block" id="rem-advanced">
        <summary className="rem-adv-summary"><b>Advanced</b> · engine internals — remediation plan, worker queue, live metrics &amp; business-risk graphs</summary>
        <div className="rem-adv-body">

          <div className="metrics">
            <div className={`metric${remLive ? ' livecard' : ''}`} title="Estimated number of issues that can be fixed automatically — populates once you run remediation"><span>auto-fixable (est.)</span><b style={{ color: remStarted ? '#3B6D11' : '#9AA1B4' }}>{remStarted ? autoFixed : 0}</b></div>
            <div className={`metric${remLive && queue.length > 0 ? ' livecard' : ''}`}>
              <span>HITL queue{remLive && queue.length > 0 && <span className="activedot" aria-hidden="true" style={{ marginLeft: 5 }} />}</span>
              {remStarted
              ? <><b key={queue.length} className={remStarted ? 'tick' : undefined} style={{ color: queue.length ? '#854F0B' : '#3B6D11' }}>{totalHitl === 0 ? 'no items' : `${queue.length} remaining`}</b>{totalHitl > 0 && <span className="muted" style={{ fontSize: 11 }}> · {hitlProgress}% done</span>}</>
              : <b style={{ color: '#9AA1B4' }}>—</b>}</div>
            {pureAutomated ? (
              <div className="metric" title="Fixed copies written back to the source Drive folder"><span>written to Drive</span><b key={written} className={written ? 'tick' : undefined} style={{ color: '#3B6D11' }}>{written}</b></div>
            ) : (
              <>
                <div className="metric"><span>approved</span><b key={acted.approved} className={acted.approved ? 'tick' : undefined}>{acted.approved}</b></div>
                <div className="metric"><span>deferred</span><b key={acted.deferred} className={acted.deferred ? 'tick' : undefined} style={{ color: '#1F5FA8' }}>{acted.deferred}</b></div>
              </>
            )}
            <div className={`metric${remLive ? ' livecard' : ''}`} title="Documents fixed and re-validated against all engines — ticks in real time as the worker queue completes each file">
              <span>re-verified{remLive && <span className="livedot">live</span>}</span>
              <b key={reVerified} className={reVerified ? 'tick' : undefined} style={{ color: '#3B6D11' }}>{reVerified.toLocaleString()}</b>
            </div>
          </div>

          <QueuePanel />

          {/* Write-back results — proof the fixed copies landed in Drive / Blob. */}
          {(written2.length > 0 || downloadOnly.length > 0) && (
            <div style={{ margin: '12px 0 14px', padding: '10px 14px', borderRadius: 9,
                          background: '#E7F0DC', border: '1px solid #C5DBA8',
                          display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: '#2F5310' }}>
                ✓ {written2.length} fixed document{written2.length !== 1 ? 's' : ''} written back to Drive
                {downloadOnly.length > 0 && ` · ${downloadOnly.length} remediated (no Drive write)`}
              </span>
              <span style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
                {written2.slice(0, 6).map((f) => (
                  <a key={f.file} href={f.drive_write_url} target="_blank" rel="noreferrer"
                     style={{ fontSize: 12, color: '#185FA5' }} title={`Open ${f.file} in the Remediated/ folder`}>
                    {f.file} ↗
                  </a>
                ))}
                {written2.length > 6 && <span className="muted" style={{ fontSize: 12 }}>+{written2.length - 6} more</span>}
                {downloadOnly.slice(0, 6).map((f) => (
                  <button key={f.file} className="ghost small" style={{ fontSize: 12 }}
                          title={`Download the fixed copy of ${f.file} (stored in Blob)`}
                          onClick={() => downloadRemediated(runId, f.file)}>
                    ⤓ {f.file}
                  </button>
                ))}
                {downloadOnly.length > 6 && <span className="muted" style={{ fontSize: 12 }}>+{downloadOnly.length - 6} more</span>}
              </span>
            </div>
          )}

          {/* Remediation plan + accept/reject/modify decisions. */}
          {plan && (
            <div className="planband">
              <div className="planhead">
                <div>
                  <b>Remediation plan</b>
                  <div className="muted" style={{ marginTop: 2 }}>
                    <b style={{ color: 'var(--ink)' }} title={EFFORT_BASIS}>{fmtEffort(plan.remediateMin)}</b> across {plan.remediableDocs} documents · <b style={{ color: '#3B6D11' }}>{plan.autoPct}% fully automatic</b>
                  </div>
                </div>
                <div className="plandec">
                  <span className="muted">{dcount('accepted')} accepted · {dcount('override')} modified · {dcount('rejected')} rejected · {pending} pending</span>
                  {autoFiles.length > 0 && (
                    <button className="batchbtn" onClick={batchAutoRemediate}
                            title="Accept ONLY the fully-automatic files — the engine fixes these deterministically when you click Remediate all. No human review involved.">
                      {/* Weight, not opacity — see the ⚠ note on the sibling button below. This one
                          still cleared 4.5:1 at 0.85 (5.15 on #1F5FA8), but the mechanism is the
                          same and a future palette tweak would have taken it under silently. */}
                      ⚡ Auto-fix {autoFiles.length} file{autoFiles.length !== 1 ? 's' : ''} <span style={{ fontWeight: 400 }}>· no review needed</span></button>
                  )}
                  <button className="acceptfullbtn" disabled={!pending} onClick={acceptAll}
                          title="Accept the WHOLE plan — every remediable file, including the ones below that need assisted or manual work from a person.">
                    {/* ⚠ White on this button's #A56814 is 4.58:1 — it clears 4.5:1 with almost no
                        margin, and `opacity: 0.85` spent that margin: the sub-label rendered at
                        3.78:1. 13px/600 is not large text, so 4.5:1 applies. Weight de-emphasises
                        it without touching the ratio. The background is left alone deliberately —
                        it passes, and re-picking a brand colour is a separate decision — but it
                        has no headroom, so anything that lightens it fails. */}
                    👥 Accept full plan · {pending}{humanCount > 0 && <span style={{ fontWeight: 400 }}> · +{humanCount} need a person</span>}
                  </button>
                </div>
              </div>
              <div className="plancards">
                {planCards.map((b) => {
                  const [label, bg, fg, icon] = REC_STYLE[b.action] || REC_STYLE.review
                  return (
                    <div className="plancard" key={b.action} style={{ background: bg }} tabIndex={0} aria-label={`${label}: ${ACTION_DESC[b.action]}`}>
                      <div className="plancardtop" style={{ color: fg }}><span>{icon}</span><b>{b.n}</b></div>
                      <div className="plancardlbl" style={{ color: fg }}>{label}</div>
                      <div className="muted plancardeta" title={EFFORT_BASIS}>{b.action === 'manual' ? `${fmtEffort(b.min)} manual` : fmtEffort(b.min)}</div>
                      <div className="plantip" role="tooltip"><b style={{ color: fg }}>{icon} {label}</b>{ACTION_DESC[b.action]}</div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {flagged.length > 0 && (
            <div className="prioritypanel">
              <div className="priorityhd"><b>Business priority</b> <span className="muted">· what to fix first — weighted by exposure, severity &amp; ownership</span></div>
              <div className="prioritynote">⚑ {pubCrit} public-facing document{pubCrit === 1 ? '' : 's'} ha{pubCrit === 1 ? 's' : 've'} critical findings and {execFlagged} are executive-owned — the highest business risk under ADA / EAA. Start here.</div>
              <div className="prioritygrid">
                <section className="ppanel"><h3>Open findings by department</h3><Bars items={deptData} cols="118px 1fr 28px" onPick={(it) => drill(`${it.label} · open findings`, `${it.value} findings`, (f) => f.department === it.label)} /></section>
                <section className="ppanel"><h3>By owner seniority</h3><Bars items={senData} cols="92px 1fr 28px" onPick={(it) => drill(`${it.label}-owned · open findings`, `${it.value} findings`, (f) => f.seniority === it.label)} /><div className="muted ppfoot">executive / director-owned content carries more reputational weight</div></section>
                <section className="ppanel"><h3>By exposure</h3><Bars items={expData} cols="98px 1fr 28px" onPick={(it) => drill(`${it.label} · open findings`, `${it.value} findings`, (f) => exposureOf(f) === it.label)} /><div className="muted ppfoot">public-facing pages are the top legal-exposure set</div></section>
              </div>
            </div>
          )}

          {remediable.length > 0 && (
            <section className="panel">
              <h2>Documents to remediate <span className="muted">· {remediable.length} · <b style={{ color: 'var(--ink)', fontWeight: 500 }}>AI-triaged</b> by business risk — exposure × severity × ownership — accept / reject / modify</span></h2>
              {ontCount > 0 && <div className="ontbanner">⬆ Ordered by your <b>business ontology</b> — {ontCount} document{ontCount === 1 ? '' : 's'} elevated by published rules (Settings → Business ontology)</div>}
              <div className="remlist">
                {remediable.map((f) => {
                  const rec = f.rec; const dec = decisions[f.file]
                  const effAction = dec?.state === 'override' ? dec.action : rec.action
                  const [label, rbg, rfg, icon] = REC_STYLE[effAction] || REC_STYLE.review
                  const effEta = dec?.state === 'override' ? (ETA_OVERRIDE[dec.action] ?? rec.etaMin) : rec.etaMin
                  const [priLabel, priFg, priBg] = PRI[priTier(f)]
                  return (
                    <div className={`remrow${dec?.state === 'rejected' ? ' rowrej' : ''}`} key={f.file} style={{ borderLeft: `3px solid ${rfg}`, paddingLeft: 10 }}>
                      <div className="remmaincol">
                        <button className="remname" onClick={() => setSel(f)}>{f.file}<span className="muted"> · {f.sourceName} · {f.department}</span>
                          {pendingHitlFiles.has(f.file) && <span className="hitlbadge">⚑ awaiting review</span>}
                        </button>
                        {f.ont ? (
                          <div className="rempri">
                            <span className="pritag" style={{ background: PRI_COLOR[f.ont.priority][1], color: PRI_COLOR[f.ont.priority][0] }}>{f.ont.priority}</span>
                            {f.ont.label && <span className="ontlabelpill" style={{ color: f.ont.label.color, background: f.ont.label.color + '22' }}>{f.ont.label.name}</span>}
                            <span className="muted">business rule: {f.ont.rule.name}{f.ont.sla ? ` · ${f.ont.sla}d SLA` : ''}</span>
                          </div>
                        ) : (
                          <div className="rempri"><span className="pritag" style={{ background: priBg, color: priFg }}>{priLabel}</span><span className="muted">why: {priWhy(f)}</span></div>
                        )}
                      </div>
                      <span className="reccell">
                        <span className="badge" style={{ background: rbg, color: rfg }}>{icon} {label}</span>
                        {dec?.state === 'accepted' && <span className="dectag ok">✓ accepted</span>}
                        {dec?.state === 'override' && <span className="dectag ov">modified</span>}
                        {dec?.state === 'rejected' && <span className="dectag rj">rejected</span>}
                        {editing === f.file ? (
                          <span className="modchips">
                            {ACTIONS.map((a) => { const [l, , fg, ic] = REC_STYLE[a]; return <button key={a} className="modchip" style={{ color: fg }} onClick={() => decide(f.file, a === rec.action ? { state: 'accepted' } : { state: 'override', action: a })}>{ic} {l}</button> })}
                            <button className="modchip cancel" onClick={() => setEditing(null)}>cancel</button>
                          </span>
                        ) : (
                          <span className="decctl">
                            {!dec ? (<>
                              <button className="decbtn ok" title="Accept" onClick={() => decide(f.file, { state: 'accepted' })}>✓</button>
                              <button className="decbtn rj" title="Reject" onClick={() => decide(f.file, { state: 'rejected' })}>✕</button>
                              <button className="decbtn ed" title="Modify action" onClick={() => setEditing(f.file)}>✎</button>
                            </>) : <button className="decbtn undo" title="Undo" onClick={() => undo(f.file)}>↺</button>}
                          </span>
                        )}
                      </span>
                      <span className="etacell" title={EFFORT_BASIS}>{fmtEffort(effEta)}</span>
                    </div>
                  )
                })}
              </div>
            </section>
          )}

          {/* Server-side remediation runner. */}
          <div className="remcta">
            <div className="remcta-label">
              {dcount('accepted') + dcount('override') > 0
                ? <span>✓ <b>{dcount('accepted') + dcount('override')}</b> file{(dcount('accepted') + dcount('override')) !== 1 ? 's' : ''} accepted — ready to remediate</span>
                : <span className="muted">Accept files above, then run remediation</span>}
              {/* A refusal is not chatter. "Nothing to remediate — of 3 documents: 3 already
                  remediated." answers the question the click asked, and must read like an
                  answer; only success stays green, only progress stays muted. */}
              {remMsg && (
                <span role="status" aria-live="polite"
                      style={{ marginLeft: 12,
                               color: remMsg.startsWith('✓') ? '#3B6D11'
                                    : remMsg.startsWith('Nothing to remediate') ? '#8A4B00'
                                    : 'var(--muted)',
                               fontWeight: remMsg.startsWith('Nothing to remediate') ? 600 : undefined }}>
                  {remMsg}
                </span>
              )}
            </div>
            <button disabled={remBusy || !runId || readOnly} onClick={() => runServerRemediation(remediable)}
                    title="Run deterministic HTML remediation server-side, in the durable worker queue. Fixed copies are written to a Remediated/ folder; results trace to Langfuse."
                    style={{ flexShrink: 0 }}>
              {remBusy ? '⏳ Enqueueing…' : '⚡ Remediate all (server-side)'}
            </button>
            {(serverFixed > 0 || remProg) && <TraceChip scanId={runId} kind="session" label="View traces in Langfuse" />}
          </div>

          {remProg && (
            <div style={{ margin: '4px 0 14px', maxWidth: 560 }} role="status" aria-live="polite">
              <div style={{ height: 9, borderRadius: 6, background: 'var(--line)', overflow: 'hidden' }}>
                <i style={{ display: 'block', height: '100%',
                            width: `${Math.round((remProg.done / Math.max(1, remProg.total)) * 100)}%`,
                            background: '#BF8C00', transition: 'width .35s' }} />
              </div>
              <div className="muted" style={{ fontSize: 12.5, marginTop: 6 }}>
                ⚡ <b>Live</b> · remediating {remProg.done.toLocaleString()} of {remProg.total.toLocaleString()} files in real time
                {remProg.latest ? <> · last fixed <span className="fname">{remProg.latest}</span></> : '…'}
                {remProg.failed ? ` · ${remProg.failed} failed` : ''}
              </div>
            </div>
          )}

          {fixTypesDisplay.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div className="advh3">Automated fixes by type</div>
              <Bars items={fixTypesDisplay} cols="140px 1fr 30px" />
            </div>
          )}

          <p className="muted" style={{ fontSize: 12, marginTop: 14 }}>
            Remediated files are stamped <b>_a11y-certified-{new Date().toISOString().split('T')[0]}</b> · originals kept for the audit trail · always written to <b>Azure Blob</b> (download from each file’s drawer), with an optional Drive mirror (Settings → Remediated storage).
          </p>
        </div>
      </details>

      {seg && <SegmentDrawer title={seg.title} subtitle={seg.subtitle} files={seg.files} onClose={() => setSeg(null)} onPickFile={(f) => { setSeg(null); setSel(f) }} />}
      {sel && <FileDrawer file={sel} context="remediate" aiEnabled={aiEnabled} scanId={run?.id} readOnly={readOnly} onClose={() => setSel(null)} />}
      {selItem && <ReviewDrawer item={selItem} onClose={() => setSelItem(null)} onAct={act} onDraft={selItem.aiDraftable ? draftAi : null} />}
    </>
  )
}

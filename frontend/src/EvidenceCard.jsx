import { useState, useEffect, useRef } from 'react'
import { getFileRemediationDiffs, suggestFix } from './api.js'
import { confClass } from './confidence.js'
import Thumbnail from './Thumbnail.jsx'
import { buildEvidenceCard, evidenceOf, firstProposed, isValueFix, proposalsOf, reviewTelemetry, thumbAlt, thumbSize } from './reviewCard.js'
import ProposalThumb from './ProposalThumb.jsx'
import ProposalEditors, { seedValues } from './ProposalEditors.jsx'

// Evidence Card (PRD v2) — a PR-style review of ONE accessibility issue. The human APPROVES
// ACP's recommendation; ACP applies it. Assembles only shipped primitives (confidence basis,
// remediationTrack, remediation_diff, thumbnail) and records review telemetry (edited flag +
// review time) so the workspace can report reviewer time saved and calibrate confidence.
//
// onAct(id, status, note, approvedValue, telemetry) — the parent owns the write, so its
// optimistic update and the queue-drain event stay wired. traceUrl is optional.
export default function EvidenceCard({ item, onAct, onResolved, traceUrl = null }) {
  const [diffs, setDiffs] = useState([])
  // One editor per proposal: the row carries one proposal per image, and a single text box
  // could never describe ten different pictures. Seeded from each image's own draft, so
  // approving without touching anything means "the drafts I was shown are correct" — the
  // server applies exactly these, per locator.
  const proposalList = proposalsOf(item)
  const [values, setValues] = useState(() => seedValues(proposalList))
  const setValueAt = (i, v) => setValues((prev) => prev.map((x, j) => (j === i ? v : x)))
  // Prefill from the server-side AI proposal when there is one — that is what turns a 30s
  // "write the alt text" into a 5s "confirm this". Falls back to a previously-approved value.
  const [value, setValue] = useState(firstProposed(item) ?? item?.approved_value ?? '')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  // A decision the server refused. Rendered as an alert — a silent failure here is a
  // reviewer believing they signed something off that was never recorded.
  const [actError, setActError] = useState(null)
  const [drafting, setDrafting] = useState(false)
  const [draftMsg, setDraftMsg] = useState(null)   // { kind: 'ai' | 'template' | 'error', text }
  // Which deferred image the reviewer is looking at. The vision model describes ONE image, so
  // a row carrying nineteen must say which — defaulting to the first silently captions the
  // wrong picture and the reviewer approves alt text for an image they never saw.
  const evidence = evidenceOf(item)
  const [picked, setPicked] = useState(0)
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
      // Which image to describe. Without this the endpoint has no image at all and 1.1.1 can
      // only ever come back as a fill-in template — the model never sees a pixel.
      const r = await suggestFix(item.scan_id, item.file, item.rule_id, evidence[picked]?.locator)
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

  const card = buildEvidenceCard(item, diffs)
  // An editor appears for every value-fix criterion, draft or not — a reviewer must be able to
  // author alt text the AI could not draft. Keying off `aiDraft != null` (as this once did)
  // silently hid the box exactly when the human was most needed.
  // An item carrying a proposal always takes a value, even if its SC isn't a classic VALUE_FIX
  // (e.g. a 1.3.3 sensory rewrite) — otherwise the reviewer sees a proposal they cannot accept.
  const editable = card.track.track !== 'auto' && (isValueFix(card.sc) || !!card.proposal)
  // "Approve & Apply" is only truthful when approval genuinely resolves the criterion. For a
  // value-fix finding nothing is applied — approving records the value as evidence and leaves
  // the document untouched — so the button must not say Apply. See card.certifiesOnApprove.
  const primaryLabel = card.certifiesOnApprove ? card.track.action : 'Approve — record sign-off'
  // One text box cannot describe N different images. Give each its own — and its own picture,
  // because a reviewer cannot honestly approve a description of an image they were never shown.
  const multi = proposalList.length > 1
  // A row with many findings but no per-instance proposals still cannot be expressed in one
  // box; there is nothing to render per image, so keep warning rather than implying it can.
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
    // What actually gets written into the document, one entry per image. Only on approval:
    // rejecting approves no content.
    const approvedValues = (status === 'approved' && proposalList.length)
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

  const b = card.confidence
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

      <div className="evcard-body" style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        {/* What the reviewer must judge — the offending image, or the rendered page for a
            reading-order proposal. Falls back to the document's page-1 render (PDF only; a
            deck cannot be rasterized). */}
        {card.thumb
          ? <ProposalThumb thumb={card.thumb} alt={thumbAlt(card.thumbKind, card.file)}
                           size={thumbSize(card.thumbKind, 96)} className="evcard-thumb" />
          : (card.scanId && card.file && <Thumbnail scanId={card.scanId} file={card.file} page={card.page || 1} className="evcard-thumb" />)}
        <div className="evcard-main" style={{ flex: 1, minWidth: 0 }}>
          <p className="evcard-problem">{card.problem}</p>

          {/* The images this row is asking for descriptions of, when the AI drafted none. One row
              can carry nineteen, so show them all: a lone thumbnail beside "19 findings" would
              say "describe this one". Selecting one is what "Draft with AI" describes — the model
              can only look at a single image, and silently picking the first would caption the
              wrong picture.

              Suppressed when the row carries proposals: ProposalEditors below already pairs every
              image with its own draft and its own editor, so the strip would show the same
              pictures twice and its picker would have nothing left to disambiguate. */}
          {evidence.length > 0 && !multi && (
            <div className="evcard-evidence">
              <span className="muted evcard-evidence-hd">
                {evidence.length === 1
                  ? 'The image needing a description'
                  : `${evidence.length} images need a description — pick one to draft or describe`}
              </span>
              <ul className="evcard-evidence-strip">
                {evidence.map((ev, i) => (
                  <li key={ev.locator || i}>
                    <button type="button" aria-pressed={i === picked}
                            className={`evcard-evidence-thumb${i === picked ? ' is-picked' : ''}`}
                            title={ev.locator || `Image ${i + 1}`}
                            onClick={() => { setPicked(i); setDraftMsg(null) }}>
                      <ProposalThumb thumb={ev.thumb} size={64} square
                                     alt={`Image ${i + 1} of ${evidence.length} in ${card.file} — needs alt text`} />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {editable && multi ? (
            <ProposalEditors proposals={proposalList} values={values}
                             onChange={setValueAt} file={card.file} />
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

          {/* Why the AI proposed this value — evidence, not a score. A proposal is a draft the
              reviewer confirms; it was never auto-applied, so the reason matters more than the
              value. When one criterion has several proposed instances, say so rather than
              silently showing only the first. */}
          {card.proposal && (
            <p className="evcard-rec-why muted" style={{ fontSize: 12, margin: '2px 0 6px' }}>
              {card.proposal.list[0]?.rationale}
              {card.proposal.list.length > 1 && ` · ${card.proposal.list.length} instances proposed on this criterion`}
            </p>
          )}

          {card.rationale && (
            <p className="evcard-rationale muted" style={{ fontSize: 12, margin: '2px 0 6px' }}>
              <b>Why this draft:</b> {card.rationale}
              {card.proposalSource && <span> · {card.proposalSource}</span>}
            </p>
          )}

          {b && (
            <p className="evcard-why">
              <span className={confClass(b.level)}>{b.level.label} confidence</span>
              <span className="muted"> · why: {b.basis}</span>
            </p>
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

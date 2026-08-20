import { useMemo, useState, useEffect, useRef } from 'react'
import {
  rowModel, laneOf, sortQueue, groupByDocument, nextUnresolvedId, progress, railColorOf,
  matchesWorkflow, workflowCounts, workflowStepIndex, isResolved, WORKFLOW_TABS, WORKFLOW_LABELS, SORTS,
} from './remediationInboxModel.js'
import { fixSteps, appName } from './remediationGuide.js'
import { scOf } from './fixSummary.js'
import { changeSentence, isContrastFinding } from './remediationEvidence.js'
import GroundedBeforeAfter from './GroundedBeforeAfter.jsx'
import RemediationPreview from './RemediationPreview.jsx'
import WorkspaceProgress from './WorkspaceProgress.jsx'
import RemediationTransform from './RemediationTransform.jsx'
import WorkspaceFooter from './WorkspaceFooter.jsx'

// Master/detail Remediation inbox. Remediation is queue work — select an item, understand it, act,
// move to the next — so the layout is a TWO-column split: a 35% work queue on the left to find and
// choose the next finding, and a 65% remediation WORKSPACE on the right that stacks, in one scrolling
// column, everything needed to finish it — Problem → Evidence → How to fix → Decision. The document
// preview is folded into the Evidence section (not a separate third pane that sat empty for every
// structure/metadata finding). Selecting a row NEVER expands it; it populates the workspace. Acting
// on a finding auto-advances to the next unresolved one, which is what makes the whole thing feel
// fast. All derivation lives in remediationInboxModel.js; this file is presentation.

const SORT_LABEL = { priority: 'Priority', document: 'Document', newest: 'Newest', fastest: 'Fastest to resolve' }
const fmtOf = (file) => String(file || '').split('.').pop().toLowerCase()
// The success-criterion key a finding shares with its siblings, used to batch a decision across
// every other queued finding of the same rule (W8). Normalised so 'SC_1_1_1' / 'WCAG 1.1.1' / '1.1.1' all match.
const scKeyOf = (f) => scOf(f?.rule_id || f?.ruleId || f?.wcag)

function LaneRail({ lane }) {
  return <span aria-hidden="true" style={{ flex: '0 0 4px', alignSelf: 'stretch', borderRadius: 4, background: railColorOf(lane) }} />
}

function Meta({ row }) {
  // Quiet metadata — WCAG, page, confidence, effort — never competing with the task heading.
  return (
    <div className="muted" style={{ display: 'flex', flexWrap: 'wrap', gap: 12, fontSize: 12, marginTop: 6 }}>
      {row.wcag && <span>WCAG {row.wcag}</span>}
      {row.location && <span>{row.location}</span>}
      {row.confidence != null && <span>Confidence {Math.round(row.confidence * 100)}%</span>}
      {row.effort && row.effort !== '—' && <span>{row.effort}</span>}
    </div>
  )
}

// `showFile` is false for rows sitting under a document group header (the header already names the
// file) and true for a standalone single-finding row (no header, so the row carries the filename).
// Either way the filename appears exactly once on screen for a given finding.
function QueueRow({ f, decisions, selected, onSelect, showFile = true }) {
  const r = rowModel(f, decisions)
  const railed = railColorOf(r.lane)
  const subline = showFile ? `${r.file}${r.location ? ` · ${r.location}` : ''}` : r.location
  return (
    <button
      type="button"
      onClick={() => onSelect(f.id)}
      aria-current={selected ? 'true' : undefined}
      className="rinbox-row"
      style={{
        display: 'flex', gap: 10, width: '100%', textAlign: 'left', cursor: 'pointer',
        padding: '10px 12px', border: 'none', borderBottom: '1px solid var(--line, #e2dce4)',
        background: selected ? 'var(--sel, #eef3ff)' : 'transparent',
        borderLeft: selected ? `3px solid ${railed}` : '3px solid transparent',
      }}
    >
      <LaneRail lane={r.lane} />
      <span style={{ minWidth: 0, flex: '1 1 auto' }}>
        {/* Dominant text is the ISSUE, not the filename — the issue determines what to do next. */}
        <span style={{ display: 'block', fontWeight: r.unread ? 700 : 500, fontSize: 13.5,
                       whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {r.issue}
        </span>
        {subline && (
          <span className="muted" style={{ display: 'block', fontSize: 12, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {subline}
          </span>
        )}
        {/* Compact chips: the WCAG SC number as the one prominent pill, then the remediation state as
            QUIET text (the lane's colour is already carried by the rail on the left, so the state does
            not need a loud coloured pill on every row). The full "what ACP did" sentence (r.did) is
            stated once in the workspace detail, never repeated per row. */}
        <span style={{ display: 'flex', gap: 8, marginTop: 4, alignItems: 'center', flexWrap: 'wrap' }}>
          {r.sc && (
            <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.02em',
                           background: 'var(--surface-2,#f0eef3)', color: 'var(--ink,#2a2340)',
                           borderRadius: 5, padding: '1px 6px',
                           fontFamily: 'var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace)' }}>
              {r.sc}
            </span>
          )}
          {r.laneShort && <span className="muted" style={{ fontSize: 11 }}>{r.laneShort}</span>}
          {r.effort !== '—' && <span className="muted" style={{ fontSize: 11 }}>{r.effort}</span>}
          {r.severity && <span className={`revcard-sev sev-${String(r.severity).toLowerCase()}`} style={{ fontSize: 10 }}>{r.severity}</span>}
          {r.resolved && <span className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>✓ resolved</span>}
        </span>
      </span>
    </button>
  )
}

function ManualSteps({ f }) {
  const fmt = fmtOf(f.file)
  const [os, setOs] = useState('win') // 'win' | 'mac'
  const steps = fixSteps(f.rule_id || f.ruleId, fmt)
  const text = steps ? (typeof steps === 'string' ? steps : steps[os] || steps.win || steps.mac) : null
  return (
    <div>
      <h4 style={{ margin: '0 0 6px' }}>Fix this in {appName(fmt)}</h4>
      <div role="tablist" aria-label="Platform" style={{ display: 'inline-flex', border: '1px solid var(--line,#e2dce4)', borderRadius: 8, overflow: 'hidden', marginBottom: 10 }}>
        {[['win', 'Windows'], ['mac', 'Mac']].map(([k, l]) => (
          <button key={k} role="tab" aria-selected={os === k} onClick={() => setOs(k)}
                  style={{ fontSize: 12, fontWeight: 600, padding: '4px 14px', cursor: 'pointer', border: 'none',
                           background: os === k ? 'var(--ink)' : 'transparent', color: os === k ? '#fff' : 'var(--ink)' }}>{l}</button>
        ))}
      </div>
      <p style={{ fontSize: 13.5, lineHeight: 1.5, margin: 0 }}>{text || 'Open the document in its native editor and correct the flagged item, then upload the revised file to recheck.'}</p>
    </div>
  )
}

// The plain, imperative "Your task" line — what a normal reviewer is expected to DO, framed as a
// remediation task rather than an engineering evidence record. Criterion- and lane-aware so a contrast
// fix reads like a contrast decision, not a generic "review the change".
function taskLineOf(f, lane) {
  const contrast = isContrastFinding(f)
  switch (lane.key) {
    case 'review':
      return contrast
        ? 'Review ACP’s contrast fix — confirm the darker text still looks right for this document, then approve it.'
        : 'Review ACP’s fix — confirm it looks right for this document, then approve it.'
    case 'apply':
      return contrast
        ? 'Review ACP’s contrast fix — confirm the darker text reads well, then apply it (or edit it first).'
        : 'Review ACP’s proposed fix — apply it, edit it first, or reject it to a person.'
    case 'handoff':
      return 'ACP’s fix was rejected — pick this one up by hand in the source app using the steps below.'
    case 'recheck':
      return 'This was edited — re-scan to confirm it now passes.'
    case 'blocked':
      return 'This can’t be remediated as-is — review what’s blocking it.'
    default: // manual
      return 'ACP can’t safely change this automatically — fix it by hand in the source app using the steps below.'
  }
}

function DetailPane({ f, decisions, onDecide, onOpenWord, onRecheck, matchingCount = 0, onApplyToMatching, scanId = null, draft = null, onDraftChange }) {
  if (!f) {
    return (
      <div style={{ display: 'grid', placeItems: 'center', height: '100%', textAlign: 'center', padding: 24 }}>
        <div className="muted">
          <div style={{ fontSize: 34 }} aria-hidden="true">✓</div>
          <p style={{ marginTop: 8 }}>Select a finding to review it here.<br />Acting on one moves you to the next automatically.</p>
        </div>
      </div>
    )
  }
  const r = rowModel(f, decisions)
  const lane = laneOf(f)
  // Handoff (a rejected AI fix, W2) is worked by hand like a manual finding — guided steps + the
  // "Mark as assigned" action — so it shares the manual detail treatment.
  const isHandoff = lane.key === 'handoff'
  const isManual = lane.key === 'manual' || isHandoff
  // A deterministic fix ACP already applied. Its decision is a plain approve / "this looks wrong",
  // not an edit-and-apply — the change is already written, so we don't offer an editable draft.
  const isAutoFix = lane.key === 'review'
  const resolved = isResolved(f, decisions)
  const eyebrow = isHandoff ? 'Needs manual handling' : lane.key === 'manual' ? 'Manual remediation' : 'Review'
  // A drafted AI value the reviewer can adjust before applying. `draft` falls back to the finding's
  // proposed value until the reviewer types; `edited` flips the primary action to "Save edited fix".
  const canEdit = !isManual && !isAutoFix && f.after != null && f.after !== ''
  const draftValue = draft ?? (f.after ?? '')
  const edited = canEdit && draftValue !== (f.after ?? '')
  // The plain-language "What ACP changed" sentence — real values only (null when nothing to describe).
  const changed = !isManual ? changeSentence(f) : null
  const hasProposedValue = f.after != null && f.after !== ''
  const sectionLabel = { fontSize: 11.5, letterSpacing: '.08em', textTransform: 'uppercase' }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ flex: '1 1 auto', overflowY: 'auto', padding: '18px 22px' }}>
        {/* 1 · What is this — and what do I need to DO about it? */}
        <p className="muted" style={{ ...sectionLabel, margin: 0 }}>{eyebrow}</p>
        <h3 style={{ margin: '4px 0 6px', fontSize: 19 }}>{r.issue}</h3>
        <p style={{ fontSize: 14, color: 'var(--ink)', margin: '0 0 4px' }}>{lane.didLine}.</p>
        <Meta row={{ ...r, wcag: (f.rule_id || f.ruleId || '') }} />

        {/* Your task — the imperative, so the reviewer is never left guessing what to do here. Hidden
            once the finding is resolved (the verification line below then speaks instead). */}
        {!resolved && (
          <div style={{ marginTop: 14, border: '1px solid var(--line,#e2dce4)', borderLeft: '3px solid var(--accent,#3b6fd6)',
                        borderRadius: 8, padding: '10px 12px', background: 'var(--surface-2,#f6f5f8)' }}>
            <p className="muted" style={{ ...sectionLabel, margin: '0 0 4px' }}>Your task</p>
            <p style={{ fontSize: 13.5, lineHeight: 1.45, margin: 0 }}>{taskLineOf(f, lane)}</p>
          </div>
        )}

        {isManual ? (
          /* Manual / handoff: there is no applied change to judge — show HOW to make it instead. */
          <div style={{ marginTop: 18 }}>
            <ManualSteps f={f} />
          </div>
        ) : (
          <>
            {/* 2 · Before / after — SEE the change, so a normal reviewer can judge whether the document
                still looks acceptable. Grounded in the finding's real before/after (contrast swatches
                with the ratio computed from the real colours, or the literal value change). */}
            <div style={{ marginTop: 18 }}>
              <p className="muted" style={{ ...sectionLabel, margin: '0 0 8px' }}>Before / after</p>
              <GroundedBeforeAfter finding={f} />
            </div>

            {/* 3 · What ACP changed — the plain sentence + the real values. */}
            {changed && (
              <div style={{ marginTop: 18 }}>
                <p className="muted" style={{ ...sectionLabel, margin: '0 0 6px' }}>What ACP changed</p>
                <p style={{ fontSize: 13.5, lineHeight: 1.5, margin: 0 }}>{changed}</p>
              </div>
            )}

            {/* Editable draft (apply lane only) — the reviewer adjusts the exact text ACP will write,
                then applies their version. Empties reset to the AI's proposal, never a blank fix.
                Preserves the #412/#415 "Save edited fix" behaviour. */}
            {canEdit && (
              <div style={{ marginTop: 14 }}>
                <label className="muted" htmlFor="rem-draft" style={{ ...sectionLabel, display: 'block', margin: '0 0 6px' }}>
                  Edit before applying
                </label>
                <textarea id="rem-draft" value={draftValue} onChange={(e) => onDraftChange?.(e.target.value)}
                          aria-label="Edit the proposed fix" rows={2}
                          style={{ width: '100%', fontSize: 13.5, padding: '8px 10px', borderRadius: 8,
                                   border: '1px solid var(--line,#e2dce4)', fontFamily: 'inherit', resize: 'vertical' }} />
                {edited && <p className="muted" style={{ fontSize: 11.5, margin: '4px 0 0' }}>Edited — “Save edited fix” writes your version instead of the AI’s.</p>}
              </div>
            )}
          </>
        )}

        {/* 5 · Supporting details — collapsed by default. Useful evidence, but NOT a substitute for
            seeing the change above. The Issue found → Proposed fix → Verified result strip lives here. */}
        {!isManual && hasProposedValue && (
          <details style={{ marginTop: 16 }}>
            <summary style={{ cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>Detection &amp; verification detail</summary>
            <div style={{ marginTop: 10 }}>
              <RemediationTransform finding={f} decisions={decisions} />  {/* Found → Proposed → Verified */}
            </div>
          </details>
        )}
        {(f.rationale || f.whyMatters) && (
          <details style={{ marginTop: 8 }}>
            <summary style={{ cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>Why this matters</summary>
            <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>{f.whyMatters || f.rationale}</p>
          </details>
        )}
        {(f.proposalSource || f.evidence) && (
          <details style={{ marginTop: 8 }}>
            <summary style={{ cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>Technical evidence &amp; audit history</summary>
            <p className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>
              {f.evidence}{f.proposalSource ? ` · source: ${f.proposalSource}` : ''}
            </p>
          </details>
        )}
      </div>

      {/* 4 · Sticky decision bar */}
      <div style={{ flex: '0 0 auto', borderTop: '1px solid var(--line,#e2dce4)', background: 'var(--bg, #fff)' }}>
        {/* W8 — batch a decision across every other queued finding of the same rule/SC. Explicit and
            reversible-feeling: it names the count, and each target routes through the same onDecide
            (so approvals re-validate and rejections hand off) as if the reviewer acted on them one by
            one. Offered only for actionable (non-manual, unresolved) findings that actually have
            matches. */}
        {!resolved && !isManual && matchingCount > 0 && (
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap',
                        padding: '10px 22px', borderBottom: '1px solid var(--line,#e2dce4)',
                        background: 'var(--surface-2,#f6f5f8)', fontSize: 12.5 }}>
            <span className="muted">
              {matchingCount} other finding{matchingCount === 1 ? '' : 's'} share this issue{f.rule_id || f.ruleId ? ` (WCAG ${scKeyOf(f)})` : ''}.
              Apply your decision to all {matchingCount + 1} matching findings:
            </span>
            <button className="ghost" style={{ fontSize: 12.5 }} onClick={() => onApplyToMatching?.(f, { state: 'accepted' })}>
              Approve all {matchingCount + 1}
            </button>
            <button className="ghost" style={{ fontSize: 12.5 }} onClick={() => onApplyToMatching?.(f, { state: 'rejected' })}>
              Reject all {matchingCount + 1}
            </button>
          </div>
        )}
        <div style={{ padding: '12px 22px', display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          {resolved ? (
            // Verification appears only AFTER a fix is saved (spec §10): the decision is recorded and a
            // fresh scan re-validates it before it can be certified — shown here, not before the work.
            <span className="muted" style={{ fontSize: 12.5, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 13, color: 'var(--ink)', fontWeight: 600 }}>✓ Saved.</span>
              <span>Verification: <b>Written</b> → Re-scan → Certified — a fresh scan confirms it before it’s certified.</span>
            </span>
          ) : isManual ? (
            <>
              {onOpenWord && <button className="primary" onClick={() => onOpenWord(f)}>Open in Word</button>}
              {onRecheck && <button className="ghost" onClick={() => onRecheck(f)}>Upload &amp; recheck</button>}
              <button className="ghost" onClick={() => onDecide?.(f, { state: 'assigned' })}>Defer</button>
              {/* Out of scope — this criterion doesn't apply to the document. Resolves the finding and
                  takes it out of the coverage denominator (persisted as an out_of_scope resolution). */}
              <button className="ghost" onClick={() => onDecide?.(f, { state: 'not_applicable' })}>Not applicable</button>
            </>
          ) : isAutoFix ? (
            /* An auto-applied fix: the change is already written, so the decision is a clear approve or
               a flag that it looks wrong — not an edit-and-apply. "This looks wrong" hands the finding
               back for a person; it does NOT auto-revert the applied change (no backend undo exists —
               see PR body), so it is labelled as a flag, not a "reject & revert". */
            <>
              <button className="primary" onClick={() => onDecide?.(f, { state: 'accepted' })}>Approve ACP’s fix</button>
              <button className="ghost" onClick={() => onDecide?.(f, { state: 'rejected' })}>This looks wrong</button>
              {onOpenWord && <button className="ghost" onClick={() => onOpenWord(f)}>Open in Word</button>}
              <button className="ghost" onClick={() => onDecide?.(f, { state: 'not_applicable' })}>Not applicable</button>
            </>
          ) : (
            <>
              <button className="primary" onClick={() => onDecide?.(f, { state: 'accepted', value: canEdit ? draftValue : undefined })}>{edited ? 'Save edited fix' : lane.action}</button>
              {/* A specific action, not a bare "Reject": declining an AI fix hands the finding to a
                  person (the handoff lane), so the label names that outcome rather than leaving the
                  reviewer to guess what "Reject" does. */}
              <button className="ghost" onClick={() => onDecide?.(f, { state: 'rejected' })}>Reject &amp; handle manually</button>
              <button className="ghost" onClick={() => onDecide?.(f, { state: 'assigned' })}>Defer</button>
              <button className="ghost" onClick={() => onDecide?.(f, { state: 'not_applicable' })}>Not applicable</button>
              {onOpenWord && <button className="ghost" onClick={() => onOpenWord(f)}>Open in Word</button>}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Workspace layout: how the guided pane and the document preview share the space beside the
// inbox. Split = side by side, Stacked = preview below the guided pane, Focus = preview hidden so
// the fix has the whole workspace (text-only fixes rarely need the render). Named to NOT collide
// with the preview's own Before/After/Side-by-side control, which is about the document diff. ──
const LAYOUTS = [
  ['split', 'Split', 'Guided remediation and document preview side by side'],
  ['stacked', 'Stacked', 'Document preview stacked below the guided pane'],
  ['focus', 'Focus', 'Hide the document preview and focus on the fix'],
]
const LAYOUT_KEYS = LAYOUTS.map(([k]) => k)

// A workspace preference (the reviewer sets it once), so it lives in localStorage keyed globally —
// unlike search/filter state, which is per-scan sessionStorage. Every access is guarded: storage
// can throw (private mode, disabled) and must never take the inbox down with it.
const LS = 'acp.remediate.'
function readLS(k, dflt) { try { const v = localStorage.getItem(LS + k); return v == null ? dflt : v } catch { return dflt } }
function readNum(k, dflt) { const n = parseFloat(readLS(k, '')); return Number.isFinite(n) ? n : dflt }
function writeLS(k, v) { try { localStorage.setItem(LS + k, String(v)) } catch { /* storage unavailable — keep the in-memory value */ } }
const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n))

// A keyboard-operable resize handle. Pointer drag resizes in the browser; Arrow keys nudge it,
// which is both an accessibility requirement for role="separator" and what makes the resize
// verifiable in jsdom (which has no layout, so getBoundingClientRect is zero and pointer math
// no-ops). aria-valuenow carries the current split so assistive tech can read the ratio.
function Divider({ orientation, label, value, min, max, onDrag, onNudge }) {
  const dragging = useRef(false)
  const vertical = orientation === 'vertical' // the bar is vertical → it divides left|right
  const down = (e) => { dragging.current = true; try { e.currentTarget.setPointerCapture(e.pointerId) } catch {} e.preventDefault() }
  const move = (e) => { if (dragging.current) onDrag(e.clientX, e.clientY) }
  const up = (e) => { dragging.current = false; try { e.currentTarget.releasePointerCapture(e.pointerId) } catch {} }
  const key = (e) => {
    const dec = vertical ? 'ArrowLeft' : 'ArrowUp'
    const inc = vertical ? 'ArrowRight' : 'ArrowDown'
    if (e.key === dec) { onNudge(-1); e.preventDefault() }
    else if (e.key === inc) { onNudge(1); e.preventDefault() }
  }
  return (
    <div role="separator" tabIndex={0} aria-label={label}
         aria-orientation={vertical ? 'vertical' : 'horizontal'}
         aria-valuenow={Math.round(value)} aria-valuemin={min} aria-valuemax={max}
         onPointerDown={down} onPointerMove={move} onPointerUp={up} onKeyDown={key}
         style={{ flex: '0 0 7px', alignSelf: 'stretch', cursor: vertical ? 'col-resize' : 'row-resize',
                  background: 'var(--line,#e2dce4)', touchAction: 'none',
                  ...(vertical ? {} : { width: '100%' }) }} />
  )
}

export default function RemediationInbox({
  queue = [], decisions = {}, onDecide, onOpenWord, onRecheck,
  initialSort = 'priority', initialTab = 'needs-review', scanId = null, initialLayout = null,
  assignees = {}, myEmail = null, onAssign,
}) {
  const [selectedId, setSelectedId] = useState(null)
  const [tab, setTab] = useState(initialTab)
  const [sort, setSort] = useState(initialSort)
  const [search, setSearch] = useState('')
  const [collapsed, setCollapsed] = useState({}) // file -> true when a document group is collapsed
  const [drafts, setDrafts] = useState({}) // finding id -> reviewer-edited proposed value (null until edited)
  const [assignedOnly, setAssignedOnly] = useState(false) // "Assigned to me" filter — files whose assignee is myEmail

  // Workspace layout + pane sizes, restored from the reviewer's last session (localStorage).
  const [layout, setLayout] = useState(() => {
    // Default to the two-column STACKED workspace (queue + one scrolling workspace column) — the
    // focused layout the redesign was built around. Reviewers who prefer side-by-side switch to
    // Split (or Focus); their choice persists in localStorage and wins over this default.
    const v = initialLayout ?? readLS('layout', 'stacked')
    return LAYOUT_KEYS.includes(v) ? v : 'stacked'
  })
  const [leftW, setLeftW] = useState(() => clamp(readNum('leftW', 28), 18, 45))   // inbox width, % of the row
  const [centerW, setCenterW] = useState(() => clamp(readNum('centerW', 34), 20, 60)) // guided width in Split, % of the row
  const [topFrac, setTopFrac] = useState(() => clamp(readNum('topFrac', 0.5), 0.25, 0.75)) // guided height in Stacked
  useEffect(() => { writeLS('layout', layout) }, [layout])
  useEffect(() => { writeLS('leftW', leftW) }, [leftW])
  useEffect(() => { writeLS('centerW', centerW) }, [centerW])
  useEffect(() => { writeLS('topFrac', topFrac) }, [topFrac])

  const rowRef = useRef(null)   // the .rinbox flex row — the frame for horizontal (column) resizes
  const wsRef = useRef(null)    // the stacked workspace column — the frame for the vertical resize
  // Drag: translate a pointer position into a percentage of the relevant frame. Guarded on a real
  // measured size, so jsdom's zero-size rects leave the value untouched (keyboard drives the tests).
  const dragLeft = (x) => { const r = rowRef.current?.getBoundingClientRect(); if (r?.width) setLeftW(clamp(((x - r.left) / r.width) * 100, 18, 45)) }
  const dragCenter = (x) => { const r = rowRef.current?.getBoundingClientRect(); if (r?.width) setCenterW(clamp(((x - r.left) / r.width) * 100 - leftW, 20, Math.max(20, 100 - leftW - 15))) }
  const dragTop = (_x, y) => { const r = wsRef.current?.getBoundingClientRect(); if (r?.height) setTopFrac(clamp((y - r.top) / r.height, 0.25, 0.75)) }

  const counts = useMemo(() => workflowCounts(queue, decisions), [queue, decisions])
  const prog = useMemo(() => progress(queue, decisions), [queue, decisions])

  // Findings whose FILE is assigned to the current reviewer — mirrors the backend's
  // files_assigned_to(decisions, email): an empty/absent email matches nothing (never "everything").
  const assignedToMe = (f) => !!myEmail && assignees[f.file] === myEmail
  const myAssignedCount = useMemo(
    () => (myEmail ? queue.filter(assignedToMe).length : 0),
    [queue, assignees, myEmail]) // eslint-disable-line react-hooks/exhaustive-deps

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    const filtered = queue.filter((f) => matchesWorkflow(f, tab, decisions) &&
      (!assignedOnly || assignedToMe(f)) &&
      (!q || rowModel(f, decisions).issue.toLowerCase().includes(q) || String(f.file).toLowerCase().includes(q)))
    return sortQueue(filtered, sort)
  }, [queue, tab, sort, search, decisions, assignedOnly, assignees, myEmail]) // eslint-disable-line react-hooks/exhaustive-deps

  // Keep a valid selection: default to the first unresolved visible row.
  useEffect(() => {
    if (selectedId != null && visible.some((f) => f.id === selectedId)) return
    const firstOpen = visible.find((f) => !isResolved(f, decisions)) || visible[0]
    setSelectedId(firstOpen ? firstOpen.id : null)
  }, [visible, selectedId, decisions])

  const selected = queue.find((f) => f.id === selectedId) || null
  const groups = useMemo(() => groupByDocument(visible), [visible])

  // W8 — every OTHER unresolved queued finding that shares this one's rule/SC. Drives the
  // "apply to all matching" count and the batch action. Restricted to the actionable approve/apply
  // lanes: a batch decision must not silently sweep in a finding a person already rejected (handoff),
  // one that needs a manual re-author, or a blocked one.
  const ACTIONABLE = new Set(['review', 'apply', 'recheck'])
  const matchingOf = (f) => {
    const sc = scKeyOf(f)
    if (!f || !sc) return []
    return queue.filter((x) => x.id !== f.id && !isResolved(x, decisions) &&
      scKeyOf(x) === sc && ACTIONABLE.has(laneOf(x).key))
  }
  const matchingCount = selected ? matchingOf(selected).length : 0

  // Act on a finding, then auto-advance to the next unresolved one — the behaviour that makes the
  // queue feel like a controlled worklist rather than a scroll through an audit report.
  function act(f, decision) {
    onDecide?.(f, decision)
    const nextDecisions = { ...decisions, [f.id]: decision }
    const nxt = nextUnresolvedId(visible, f.id, nextDecisions)
    setSelectedId(nxt)
  }

  // W8 — apply one decision to the current finding AND every matching one, in a single click. Each
  // target routes through the same onDecide as an individual action, so approvals still re-validate
  // and rejections still hand off; then advance past everything just decided.
  function applyToMatching(f, decision) {
    const targets = [f, ...matchingOf(f)]
    const nextDecisions = { ...decisions }
    targets.forEach((t) => { onDecide?.(t, decision); nextDecisions[t.id] = decision })
    setSelectedId(nextUnresolvedId(visible, f.id, nextDecisions))
  }

  // Explicit linear navigation through the visible queue — Previous / Next step the SELECTION without
  // acting, so a reviewer can look before deciding and always sees their place ("N of M").
  const visIds = visible.map((f) => f.id)
  const curIdx = visIds.indexOf(selectedId)
  const position = curIdx >= 0 ? curIdx + 1 : 0
  const goPrev = () => { if (curIdx > 0) setSelectedId(visIds[curIdx - 1]) }
  const goNext = () => { if (curIdx >= 0 && curIdx < visIds.length - 1) setSelectedId(visIds[curIdx + 1]) }

  // The two workspace panes, defined once and placed differently per layout (side by side, stacked,
  // or guided-only). The layout toggle sits on the guided header — the pane that is always shown.
  const guidedHeader = (
    <div style={{ flex: '0 0 auto', padding: '8px 12px', borderBottom: '1px solid var(--line,#e2dce4)',
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
      <span style={{ fontSize: 13, fontWeight: 700 }}>Guided remediation</span>
      <div role="group" aria-label="Workspace layout"
           style={{ display: 'inline-flex', border: '1px solid var(--line,#e2dce4)', borderRadius: 8, overflow: 'hidden' }}>
        {LAYOUTS.map(([key, label, title]) => (
          <button key={key} type="button" aria-pressed={layout === key} title={title} onClick={() => setLayout(key)}
                  style={{ fontSize: 11.5, padding: '4px 9px', cursor: 'pointer', border: 'none',
                           borderLeft: key === 'split' ? 'none' : '1px solid var(--line,#e2dce4)',
                           background: layout === key ? 'var(--accent,#3b6fd6)' : 'var(--bg,#fff)',
                           color: layout === key ? '#fff' : 'inherit', fontWeight: layout === key ? 700 : 500 }}>
            {label}
          </button>
        ))}
      </div>
    </div>
  )
  const guidedBody = (
    <DetailPane f={selected} decisions={decisions} onDecide={act} onOpenWord={onOpenWord} onRecheck={onRecheck}
                matchingCount={matchingCount} onApplyToMatching={applyToMatching}
                scanId={selected?.scanId || scanId}
                draft={selected ? (drafts[selected.id] ?? null) : null}
                onDraftChange={(v) => selected && setDrafts((d) => ({ ...d, [selected.id]: v }))} />
  )
  const previewHeader = (
    <div style={{ flex: '0 0 auto', padding: '10px 12px', borderBottom: '1px solid var(--line,#e2dce4)', fontSize: 13, fontWeight: 700 }}>Document preview</div>
  )
  const previewBody = <RemediationPreview finding={selected} scanId={selected?.scanId || scanId} />

  return (
    <div className="rinbox-wrap">
      {/* Dark app header (mockup): the section title + the workflow-status tabs as the page's top
          chrome — one lens on where every finding sits in the pipeline (Inbox → In progress →
          Ready to validate → Blocked → Done), spanning the three panes below. */}
      <div className="rinbox-topbar" role="tablist" aria-label="Workflow status"
           style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap',
                    background: '#1f2b3a', color: '#fff', borderRadius: '12px 12px 0 0', padding: '9px 16px' }}>
        <span style={{ fontWeight: 800, fontSize: 15, letterSpacing: '-.01em' }}>Remediate</span>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {WORKFLOW_TABS.map((t) => (
            <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
                    style={{ fontSize: 12, padding: '3px 11px', borderRadius: 20, cursor: 'pointer',
                             border: `1px solid ${tab === t ? 'transparent' : 'rgba(255,255,255,.22)'}`,
                             background: tab === t ? '#3b6fd6' : 'transparent', color: '#fff',
                             fontWeight: tab === t ? 700 : 500 }}>
              {WORKFLOW_LABELS[t]} {counts[t] > 0 ? counts[t] : ''}
            </button>
          ))}
        </div>
      </div>
      {/* Persistent progress bar — the selected document's remediation progress + ETA, above the panes. */}
      <WorkspaceProgress queue={queue} decisions={decisions} selected={selected} />
      <div className="rinbox" data-layout={layout} ref={rowRef} style={{ display: 'flex', gap: 0, border: '1px solid var(--line,#e2dce4)', borderRadius: '0 0 12px 12px', overflow: 'hidden', minHeight: 480 }}>
      {/* ── Left: the work queue — find and select the next finding (resizable) ── */}
      <div style={{ flex: `0 0 ${leftW}%`, maxWidth: `${leftW}%`, display: 'flex', flexDirection: 'column', minHeight: 480 }}>
        <div style={{ flex: '0 0 auto', padding: '10px 12px', borderBottom: '1px solid var(--line,#e2dce4)' }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>Remediation Inbox</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input type="search" value={search} onChange={(e) => setSearch(e.target.value)}
                   placeholder="Search documents" aria-label="Search documents"
                   style={{ flex: '1 1 auto', minWidth: 0, fontSize: 13, padding: '6px 10px', borderRadius: 8, border: '1px solid var(--line,#e2dce4)' }} />
            <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort findings" title="Sort findings"
                    style={{ flex: '0 0 auto', fontSize: 11.5, padding: '5px 6px', borderRadius: 6, border: '1px solid var(--line,#e2dce4)' }}>
              {SORTS.map((s) => <option key={s} value={s}>{SORT_LABEL[s]}</option>)}
            </select>
          </div>
          {/* "Assigned to me" filter + a context assign chip for the selected document. Mirrors the
              #417 backend (files_assigned_to); shown only for a signed-in reviewer with an assign
              action, so it is never a dead control. Assigning is per-DOCUMENT (a file's whole set of
              findings), which is how the backend keys the assignee. */}
          {myEmail && onAssign && (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginTop: 8 }}>
              <button type="button" onClick={() => setAssignedOnly((v) => !v)} aria-pressed={assignedOnly}
                      title="Show only findings in documents assigned to you"
                      style={{ fontSize: 11.5, fontWeight: 600, padding: '3px 10px', borderRadius: 20, cursor: 'pointer',
                               border: `1px solid ${assignedOnly ? 'transparent' : 'var(--line,#e2dce4)'}`,
                               background: assignedOnly ? 'var(--accent,#3b6fd6)' : 'var(--bg,#fff)',
                               color: assignedOnly ? '#fff' : 'inherit' }}>
                Assigned to me{myAssignedCount > 0 ? ` (${myAssignedCount})` : ''}
              </button>
              {selected && (assignees[selected.file] === myEmail
                ? <button type="button" onClick={() => onAssign(selected.file, null)}
                          title={`Unassign ${selected.file} from you`}
                          style={{ fontSize: 11.5, padding: '3px 10px', borderRadius: 20, cursor: 'pointer',
                                   border: '1px solid var(--line,#e2dce4)', background: 'var(--bg,#fff)', color: 'inherit' }}>
                    ✓ Assigned to you
                  </button>
                : <button type="button" onClick={() => onAssign(selected.file, myEmail)}
                          title={`Assign ${selected.file} to you`}
                          style={{ fontSize: 11.5, padding: '3px 10px', borderRadius: 20, cursor: 'pointer',
                                   border: '1px solid var(--line,#e2dce4)', background: 'var(--bg,#fff)', color: 'var(--muted,#5b6774)' }}>
                    + Assign to me
                  </button>)}
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
            {/* "reviewed" (a decision is recorded), NOT "resolved" — an approved fix awaiting the
                re-scan is reviewed but not yet Completed, so this never contradicts the tab counts. */}
            <span className="muted" style={{ fontSize: 11.5, fontWeight: 600 }}>{prog.resolved} of {prog.total} reviewed</span>
          </div>
        </div>
        <div style={{ flex: '1 1 auto', overflowY: 'auto' }}>
          {visible.length === 0 ? (
            <p className="muted" style={{ padding: 16, fontSize: 13 }}>
              {assignedOnly
                ? <>Nothing in this view is assigned to you. <button className="linklike" onClick={() => setAssignedOnly(false)}>Show all</button></>
                : <>Nothing here. {tab !== 'needs-review' && <button className="linklike" onClick={() => setTab('needs-review')}>Back to Needs review</button>}</>}
            </p>
          ) : groups.map((g) => (
            // A document with a SINGLE finding needs no expandable group header — the row itself
            // names the file. Only multi-finding documents get the collapsible 📄 header, so the file
            // is stated once either way.
            g.items.length === 1 ? (
              <QueueRow key={g.items[0].id} f={g.items[0]} decisions={decisions}
                        selected={g.items[0].id === selectedId} onSelect={setSelectedId} showFile />
            ) : (
              <div key={g.file}>
                <button type="button" onClick={() => setCollapsed((c) => ({ ...c, [g.file]: !c[g.file] }))}
                        style={{ display: 'flex', width: '100%', alignItems: 'center', gap: 8, padding: '6px 12px', cursor: 'pointer',
                                 border: 'none', borderBottom: '1px solid var(--line,#e2dce4)', background: 'var(--surface-2,#f6f5f8)', fontSize: 12, fontWeight: 700 }}>
                  <span aria-hidden="true">{collapsed[g.file] ? '▸' : '▾'}</span>
                  <span style={{ flex: '1 1 auto', minWidth: 0, textAlign: 'left', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>📄 {g.file}</span>
                  <span className="muted" style={{ fontWeight: 400 }}>{g.items.length}</span>
                </button>
                {!collapsed[g.file] && g.items.map((f) => (
                  <QueueRow key={f.id} f={f} decisions={decisions} selected={f.id === selectedId} onSelect={setSelectedId} showFile={false} />
                ))}
              </div>
            )
          ))}
        </div>
      </div>

      {/* Divider between the inbox and the workspace — present in every layout. */}
      <Divider orientation="vertical" label="Resize the inbox" value={leftW} min={18} max={45}
               onDrag={dragLeft} onNudge={(d) => setLeftW((w) => clamp(w + d * 2, 18, 45))} />

      {layout === 'stacked' ? (
        /* ── Stacked: guided remediation above, document preview below, one workspace column ── */
        <div ref={wsRef} style={{ flex: '1 1 auto', minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 480 }}>
          <div style={{ flex: `0 0 ${topFrac * 100}%`, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
            {guidedHeader}
            <div style={{ flex: '1 1 auto', minHeight: 0 }}>{guidedBody}</div>
          </div>
          <Divider orientation="horizontal" label="Resize the document preview" value={topFrac * 100} min={25} max={75}
                   onDrag={dragTop} onNudge={(d) => setTopFrac((t) => clamp(t + d * 0.05, 0.25, 0.75))} />
          <div style={{ flex: '1 1 auto', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
            {previewHeader}
            <div style={{ flex: '1 1 auto', minHeight: 0, overflowY: 'auto' }}>{previewBody}</div>
          </div>
        </div>
      ) : (
        <>
          {/* ── Centre: guided remediation — problem → proposed change → decision, one at a time ── */}
          <div style={{ flex: layout === 'focus' ? '1 1 auto' : `0 0 ${centerW}%`, maxWidth: layout === 'focus' ? 'none' : `${centerW}%`,
                        minWidth: 0, display: 'flex', flexDirection: 'column' }}>
            {guidedHeader}
            <div style={{ flex: '1 1 auto', minHeight: 0 }}>{guidedBody}</div>
          </div>

          {/* ── Right: document preview (Split only — hidden in Focus) ── */}
          {layout === 'split' && (
            <>
              <Divider orientation="vertical" label="Resize the document preview" value={centerW} min={20} max={60}
                       onDrag={dragCenter} onNudge={(d) => setCenterW((w) => clamp(w + d * 2, 20, Math.max(20, 100 - leftW - 15)))} />
              <div style={{ flex: '1 1 auto', minWidth: 0, display: 'flex', flexDirection: 'column' }}>
                {previewHeader}
                <div style={{ flex: '1 1 auto', minHeight: 0, overflowY: 'auto' }}>{previewBody}</div>
              </div>
            </>
          )}
        </>
      )}
      </div>
      {/* Sticky workflow guide (Show → Review → Verify) + Previous / N of M / Next navigation. */}
      <WorkspaceFooter position={position} total={visIds.length} onPrev={goPrev} onNext={goNext}
                       activeStep={selected ? workflowStepIndex(selected, decisions) : null} />
    </div>
  )
}

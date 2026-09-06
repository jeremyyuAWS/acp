import { useMemo, useState, useEffect, useRef } from 'react'
import {
  rowModel, laneOf, sortQueue, groupByDocument, nextUnresolvedId, progress, railColorOf,
  matchesWorkflow, workflowCounts, workflowStepIndex, isResolved, WORKFLOW_TABS, WORKFLOW_LABELS, SORTS,
} from './remediationInboxModel.js'
import { clusterRows, clusterOfFinding, batchTargetsOf } from './remediationClusters.js'
import { fixSteps, appName } from './remediationGuide.js'
import { scOf } from './fixSummary.js'
import { changeSentence, isContrastFinding } from './remediationEvidence.js'
import WorkspaceProgress from './WorkspaceProgress.jsx'
import WorkspaceFooter from './WorkspaceFooter.jsx'
import './RemediationInbox.css'

// Master/detail Remediation inbox. Remediation is queue work — select an item, understand it, act,
// move to the next — so the layout is a TWO-column split: a 35% work queue on the left to find and
// choose the next finding, and a 65% remediation WORKSPACE on the right that stacks, in one scrolling
// column, everything needed to finish it — Problem → Evidence → How to fix → Decision. Full-document
// viewing is an explicit action instead of a persistent third pane. Selecting a row NEVER expands
// it; it populates the workspace. Acting
// on a finding auto-advances to the next unresolved one, which is what makes the whole thing feel
// fast. All derivation lives in remediationInboxModel.js; this file is presentation.

const SORT_LABEL = { priority: 'Priority', document: 'Document', newest: 'Newest', fastest: 'Fastest to resolve' }
const fmtOf = (file) => String(file || '').split('.').pop().toLowerCase()
// The success-criterion key a finding shares with its siblings, used to batch a decision across
// every other queued finding of the same rule (W8). Normalised so 'SC_1_1_1' / 'WCAG 1.1.1' / '1.1.1' all match.
const scKeyOf = (f) => scOf(f?.rule_id || f?.ruleId || f?.wcag)
const LARGE_BATCH_THRESHOLD = 10

const WHY_BY_SC = {
  '1.1.1': 'Text alternatives let screen-reader users understand images and other non-text content.',
  '1.3.1': 'Programmatic structure helps assistive technology identify headings, lists, tables, and relationships.',
  '1.3.2': 'A meaningful reading order ensures content makes sense when it is read aloud or navigated without its visual layout.',
  '1.4.3': 'Sufficient contrast makes text easier to read for people with low vision and in difficult viewing conditions.',
  '2.4.2': 'A descriptive document title helps people identify the document and distinguish it from other open content.',
  '2.4.4': 'Descriptive link text helps people understand a link’s destination without relying on surrounding context.',
  '3.1.1': 'The correct document language helps screen readers pronounce and interpret the content accurately.',
  '3.1.2': 'Correct language metadata helps screen readers pronounce passages written in another language.',
  '4.1.2': 'Accessible names and roles let assistive technology identify controls and explain how to use them.',
}

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

// Detector payloads occasionally contain serialized HTML entities. They are data, not markup, so
// decode the small HTML entity surface we display without using dangerouslySetInnerHTML.
function displayText(value) {
  return String(value ?? '')
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
    .replace(/&#x([\da-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
    .replace(/&nbsp;/gi, '\u00a0').replace(/&amp;/gi, '&').replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>').replace(/&quot;/gi, '"').replace(/&apos;|&#39;/gi, "'")
}

function problemOf(f, issue) {
  if (f.problemStatement) return displayText(f.problemStatement)
  const before = displayText(f.before || f.observed || '')
  const after = displayText(f.after || '')
  if (before && after) return `ACP found ${before} where ${after} is recommended.`
  return `ACP found an issue with ${issue.toLowerCase()} in this document.`
}

function whyOf(f) {
  return displayText(f.whyMatters || f.rationale || WHY_BY_SC[scKeyOf(f)]
    || 'Correcting this issue helps people using assistive technology understand and use the document.')
}

// Highlight only the characters that changed. The full value remains in the accessible label, so
// screen readers receive a clean comparison rather than punctuation around separate fragments.
function ChangedValue({ from, to }) {
  const a = displayText(from)
  const b = displayText(to)
  if (!a || !b || a === b) return <>{b || 'Not recorded'}</>
  let start = 0
  while (start < a.length && start < b.length && a[start] === b[start]) start += 1
  let end = 0
  while (end < a.length - start && end < b.length - start && a[a.length - 1 - end] === b[b.length - 1 - end]) end += 1
  const prefix = b.slice(0, start)
  const changed = b.slice(start, b.length - end || undefined)
  const suffix = end ? b.slice(-end) : ''
  return <>{prefix}{changed && <mark className="remediation-change">{changed}</mark>}{suffix}</>
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
      id={`rinbox-row-${f.id}`}
      onClick={() => onSelect(f.id)}
      aria-current={selected ? 'true' : undefined}
      // Roving tabindex: only the selected row is a Tab stop; Arrow/j-k keys move between rows (handled
      // on the list container), so a keyboard user reaches the queue in ONE tab and steps through it.
      tabIndex={selected ? 0 : -1}
      // A clean spoken label — the issue, its document, and the remediation state — instead of the
      // raw concatenation of the visible chips.
      aria-label={`${r.issue}, ${r.file}${r.location ? `, ${r.location}` : ''}${r.laneShort ? ` — ${r.laneShort}` : ''}`}
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
          {f?.status === 'in_review' && !r.resolved && (
            <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: '.04em',
                           background: 'var(--accent-subtle,#e8f0fe)', color: 'var(--accent,#3b6fd6)',
                           borderRadius: 4, padding: '1px 5px', marginLeft: 'auto' }}>
              In review
            </span>
          )}
          {r.resolved && <span className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>✓ resolved</span>}
        </span>
      </span>
    </button>
  )
}

// ── A CLUSTER row: many findings, one decision ────────────────────────────────────────────────
// The row a reviewer actually works. A production run put 265 findings into this queue, largely for
// one criterion; a queue that long invites rubber-stamping however well each row is laid out. So the
// unit of the queue is the cluster — same criterion, same format, same lane — and the reviewer
// inspects ONE representative and decides once for the group.
//
// Two controls, side by side, because one button cannot legally contain another: the row itself
// selects the cluster's shown finding, and a separate disclosure expands the members so any
// individual one can still be inspected and decided on its own.
// The formats a cluster spans, as reading text. Format is NOT part of the cluster key, so a group
// can cover .docx and .pdf at once; this is what keeps that breadth visible instead of implied.
function formatList(formats) {
  const f = (formats || []).map((x) => String(x).toUpperCase())
  if (f.length === 0) return ''
  if (f.length === 1) return f[0]
  if (f.length === 2) return `${f[0]} and ${f[1]}`
  return `${f.slice(0, -1).join(', ')} and ${f[f.length - 1]}`
}

const SEV_ORDER = ['CRITICAL', 'SERIOUS', 'MODERATE', 'MINOR', 'UNRATED']
function severityLine(severities) {
  const parts = SEV_ORDER.filter((k) => severities?.[k]).map((k) => `${severities[k]} ${k === 'UNRATED' ? 'unrated' : k.toLowerCase()}`)
  return parts.join(' · ')
}

function ClusterRow({ row, shown, decisions, selectedId, onSelect, expanded, onToggle }) {
  const r = rowModel(shown, decisions)
  const railed = railColorOf(row.lane)
  const sevLine = severityLine(row.severities)
  const remaining = row.unresolved.length
  const listId = `rinbox-cluster-${row.key.replace(/[^\w-]/g, '_')}`
  // When collapsed the header IS the selected member's row, so it carries the selection. When
  // expanded the member rows carry it, and the header steps back — exactly one row is current.
  const selected = !expanded && shown.id === selectedId
  // Spoken as one unit: what the group is, how big it is, and how much of it is left — the three
  // facts that decide whether a reviewer opens it. The per-member rows carry their own labels.
  const label = `${r.issue}, ${row.count} findings across ${row.fileCount} document${row.fileCount === 1 ? '' : 's'}`
    + `, ${formatList(row.formats)}${row.lane?.short ? ` — ${row.lane.short}` : ''}`
    + `, ${remaining} awaiting a decision`
  return (
    <div className="rinbox-clusterwrap">
      <div style={{ display: 'flex', alignItems: 'stretch', borderBottom: '1px solid var(--line, #e2dce4)',
                    background: selected ? 'var(--sel, #eef3ff)' : 'transparent',
                    borderLeft: selected ? `3px solid ${railed}` : '3px solid transparent' }}>
        <button
          type="button"
          id={`rinbox-row-${shown.id}`}
          onClick={() => onSelect(shown.id)}
          aria-current={selected ? 'true' : undefined}
          tabIndex={selected ? 0 : -1}
          aria-label={label}
          className="rinbox-row rinbox-cluster-row"
          style={{ display: 'flex', gap: 10, flex: '1 1 auto', minWidth: 0, textAlign: 'left',
                   cursor: 'pointer', padding: '10px 12px', border: 'none', background: 'transparent' }}
        >
          <LaneRail lane={row.lane} />
          <span style={{ minWidth: 0, flex: '1 1 auto' }}>
            <span style={{ display: 'block', fontWeight: remaining > 0 ? 700 : 500, fontSize: 13.5,
                           whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {r.issue}
            </span>
            {/* The scale of the group, which is the reason it is one row instead of many. */}
            <span className="muted" style={{ display: 'block', fontSize: 12 }}>
              {row.count} findings · {row.fileCount} document{row.fileCount === 1 ? '' : 's'}
            </span>
            <span style={{ display: 'flex', gap: 8, marginTop: 4, alignItems: 'center', flexWrap: 'wrap' }}>
              {row.sc && (
                <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.02em',
                               background: 'var(--surface-2,#f0eef3)', color: 'var(--ink,#2a2340)',
                               borderRadius: 5, padding: '1px 6px',
                               fontFamily: 'var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace)' }}>
                  {row.sc}
                </span>
              )}
              <span className="muted" style={{ fontSize: 11 }}>{formatList(row.formats)}</span>
              {row.lane?.short && <span className="muted" style={{ fontSize: 11 }}>{row.lane.short}</span>}
              {/* The severity MIX, stated rather than hidden: severity is not part of the cluster key
                  (it would fragment every large group), so the reviewer must be able to see that a
                  batch spans a critical and a minor finding before they decide it. */}
              {sevLine && <span className="muted" style={{ fontSize: 11 }}>{sevLine}</span>}
              {row.resolvedCount > 0 && (
                <span className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
                  {row.resolvedCount} of {row.count} decided
                </span>
              )}
            </span>
          </span>
        </button>
        <button
          type="button"
          onClick={() => onToggle(row.key)}
          aria-expanded={expanded}
          aria-controls={listId}
          aria-label={`${expanded ? 'Collapse' : 'Expand'} the ${row.count} findings in ${r.issue}`}
          style={{ flex: '0 0 auto', border: 'none', borderLeft: '1px solid var(--line,#e2dce4)',
                   background: 'transparent', cursor: 'pointer', padding: '0 12px', fontSize: 12,
                   color: 'var(--muted,#5b6774)' }}
        >
          <span aria-hidden="true">{expanded ? '\u25be' : '\u25b8'}</span>
        </button>
      </div>
      {expanded && (
        <div id={listId} style={{ background: 'var(--surface-2,#faf9fb)' }}>
          {row.items.map((f) => (
            <QueueRow key={f.id} f={f} decisions={decisions} selected={f.id === selectedId}
                      onSelect={onSelect} showFile />
          ))}
        </div>
      )}
    </div>
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
      {/* Present only on the criteria a menu path cannot resolve (1.4.1, 1.4.11, 2.1.2, 2.4.3).
          Knowing where to click does not tell a reviewer when they are DONE, and for these ACP
          cannot check the result at all — saying so is what separates guidance from a false
          sense of completion. Empty for every other criterion, so nothing renders. */}
      {steps?.completion && (
        <p style={{ fontSize: 13.5, lineHeight: 1.5, margin: '10px 0 0' }}>
          <b>Done when:</b> {steps.completion}
        </p>
      )}
      {steps?.limits && (
        <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.5, margin: '8px 0 0' }}>
          <b>ACP cannot verify this:</b> {steps.limits}
        </p>
      )}
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

function DetailPane({ f, decisions, onDecide, onOpenWord, onRecheck, matchingFindings = [], onApplyToMatching, cluster = null, draft = null, onDraftChange, saving = false, error = null, headingRef = null, detailExtra = null, emptyState = null }) {
  const [matchingPreviewOpen, setMatchingPreviewOpen] = useState(false)
  const [copiedValue, setCopiedValue] = useState('')
  const draftRef = useRef(null)
  useEffect(() => { setMatchingPreviewOpen(false) }, [f?.id])
  useEffect(() => { setCopiedValue('') }, [f?.id])
  if (!f) {
    return (
      <div style={{ display: 'grid', placeItems: 'center', height: '100%', textAlign: 'center', padding: 24 }}>
        <div className="muted">
          <div style={{ fontSize: 34 }} aria-hidden="true">✓</div>
          {emptyState || <p style={{ marginTop: 8 }}>Select a finding from the inbox to review its recommended action.</p>}
        </div>
      </div>
    )
  }
  const r = rowModel(f, decisions)
  const matchingCount = matchingFindings.length
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
  const currentValue = displayText(f.before || f.observed || 'Not recorded')
  const proposedValue = displayText(draftValue || f.after || '')
  const copyValue = async (kind, value) => {
    if (!navigator.clipboard?.writeText) return
    await navigator.clipboard.writeText(value)
    setCopiedValue(kind)
  }
  const why = whyOf(f)
  const decideForGroup = (decision) => {
    if (matchingCount > LARGE_BATCH_THRESHOLD) {
      const ok = window.confirm(`Apply this decision to ${matchingCount + 1} findings across ${new Set([f.file, ...matchingFindings.map((x) => x.file)]).size} documents?`)
      if (!ok) return
    }
    return onApplyToMatching?.(f, decision)
  }
  return (
    <div className="remediation-detail" style={{ display: 'flex', flexDirection: 'column' }}>
      {/* Keep this content-sized. The workspace owns scrolling; making this child 100% tall
          pushed the decision bar to the bottom of a tall review canvas and left a large blank
          region between the evidence accordions and their actions. */}
      <div className="remediation-detail-content" style={{ padding: '18px 22px' }}>
        {/* 1 · What is this — and what do I need to DO about it? */}
        <div className="remediation-review-header">
          <p className="muted" style={{ margin: 0, fontSize: 12, fontWeight: 600 }}>{eyebrow}</p>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
            <div style={{ minWidth: 0 }}>
              <h3 ref={headingRef} tabIndex="-1" style={{ margin: '4px 0 4px', fontSize: 20 }}>{displayText(r.issue)}</h3>
              <p className="muted" style={{ margin: 0, fontSize: 13, overflowWrap: 'anywhere' }}>{displayText(r.file)}</p>
            </div>
            {onOpenWord && <button className="ghost" onClick={() => onOpenWord(f)}>View full document</button>}
          </div>
          <Meta row={{ ...r, wcag: (f.rule_id || f.ruleId || '') }} />
        </div>
        <p style={{ fontSize: 15, lineHeight: 1.55, margin: '18px 0 0' }}>{problemOf(f, r.issue)}</p>

        {/* Your task — the imperative, so the reviewer is never left guessing what to do here. Hidden
            once the finding is resolved (the verification line below then speaks instead). */}
        {!resolved && (
          <p style={{ fontSize: 13.5, lineHeight: 1.5, margin: '10px 0 0' }}><b>Your task:</b> {taskLineOf(f, lane)}</p>
        )}

        {isManual ? (
          /* Manual / handoff: there is no applied change to judge — show HOW to make it instead. */
          <div style={{ marginTop: 18 }}>
            <ManualSteps f={f} />
          </div>
        ) : (
          <>
            <div className="remediation-comparison" aria-label="Current and proposed values">
              <div><b>Current</b><span aria-label={`Current value: ${currentValue}`}>{currentValue}</span><button type="button" className="linklike remediation-copy-value" onClick={() => copyValue('current', currentValue)}>{copiedValue === 'current' ? 'Copied' : 'Copy current'}</button></div>
              <div><b>Proposed</b><span aria-label={`Proposed value: ${proposedValue}`}><ChangedValue from={currentValue} to={proposedValue} /></span><button type="button" className="linklike remediation-copy-value" onClick={() => copyValue('proposed', proposedValue)}>{copiedValue === 'proposed' ? 'Copied' : 'Copy proposed'}</button></div>
            </div>
            {changed && <p style={{ fontSize: 13.5, lineHeight: 1.5, margin: '10px 0 0' }}>{displayText(changed)}</p>}

            {/* Editable draft (apply lane only) — the reviewer adjusts the exact text ACP will write,
                then applies their version. Empties reset to the AI's proposal, never a blank fix.
                Preserves the #412/#415 "Save edited fix" behaviour. */}
            {canEdit && (
              <div style={{ marginTop: 14 }}>
                <label className="muted" htmlFor="rem-draft" style={{ display: 'block', margin: '0 0 6px', fontSize: 12, fontWeight: 600 }}>Edit proposed value</label>
                <textarea ref={draftRef} id="rem-draft" value={draftValue} onChange={(e) => onDraftChange?.(e.target.value)}
                          aria-label="Edit the proposed fix" rows={2}
                          style={{ width: '100%', fontSize: 13.5, padding: '8px 10px', borderRadius: 8,
                                   border: '1px solid var(--line,#e2dce4)', fontFamily: 'inherit', resize: 'vertical' }} />
                {edited && <p className="muted" style={{ fontSize: 11.5, margin: '4px 0 0' }}>Edited — “Save edited fix” writes your version instead of the AI’s.</p>}
              </div>
            )}
          </>
        )}

        {!isManual && <p className="muted" style={{ fontSize: 13, lineHeight: 1.45, margin: '14px 0 0' }}>
          {onRecheck ? 'After approval, ACP will create a corrected copy and verify this criterion again.'
                     : 'This change requires human confirmation; ACP cannot verify its meaning automatically.'}
        </p>}
        <section aria-labelledby="why-this-matters" style={{ marginTop: 18 }}>
          <h4 id="why-this-matters" style={{ margin: '0 0 5px', fontSize: 14 }}>Why this matters</h4>
          <p className="muted" style={{ fontSize: 13, lineHeight: 1.5, margin: 0 }}>{why}</p>
        </section>

        {!isManual && hasProposedValue && (
          <details style={{ marginTop: 16 }}>
            <summary style={{ cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>Detection and verification details</summary>
            <dl className="remediation-details-list">
              <div><dt>How ACP detected this</dt><dd>{displayText(f.detectionMethod || f.proposalSource || 'Automated document analysis')}</dd></div>
              <div><dt>Observed value</dt><dd>{currentValue}</dd></div>
              <div><dt>Verification</dt><dd>{onRecheck ? `The corrected copy will be rescanned for WCAG ${scKeyOf(f) || 'compliance'}.` : 'Human confirmation required.'}</dd></div>
              <div><dt>Current verification state</dt><dd>{resolved ? 'Awaiting verification' : 'Awaiting approval'}</dd></div>
            </dl>
          </details>
        )}
        {(f.proposalSource || f.evidence) && (
          <details style={{ marginTop: 8 }}>
            <summary style={{ cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>Technical evidence</summary>
            <p className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>
              {f.evidence}{f.proposalSource ? ` · source: ${f.proposalSource}` : ''}
            </p>
          </details>
        )}
        {detailExtra}
      </div>

      {/* 4 · Decision bar — follows the evidence so actions stay visually connected to it. */}
      <div className="remediation-detail-actions" role="group" aria-label={`Decision actions for ${displayText(r.issue)}`}
           style={{ borderTop: '1px solid var(--line,#e2dce4)', background: 'var(--bg, #fff)' }}>
        {/* W8 — batch a decision across every other queued finding of the same rule/SC. Explicit and
            reversible-feeling: it names the count, and each target routes through the same onDecide
            (so approvals re-validate and rejections hand off) as if the reviewer acted on them one by
            one. Offered only for actionable (non-manual, unresolved) findings that actually have
            matches. */}
        {!resolved && !isManual && matchingCount > 0 && (
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap',
                        padding: '10px 22px', borderBottom: '1px solid var(--line,#e2dce4)',
                        background: 'var(--surface-2,#f6f5f8)', fontSize: 12.5 }}>
            {/* The scope, stated in full before the decision. A batch is the one control here that
                reaches findings the reviewer has not looked at, so it names the criterion, the format,
                the number of documents, and — because severity is deliberately not part of what
                groups a cluster — the severity mix it spans. */}
            <span className="muted">
              You are looking at one of {matchingCount + 1} findings that share this issue
              {cluster ? <> — {scKeyOf(f) ? `WCAG ${scKeyOf(f)}` : 'the same criterion'} in {formatList(cluster.formats)} files,
                across {cluster.fileCount} document{cluster.fileCount === 1 ? '' : 's'}</> : null}.
              {cluster && cluster.formats.length > 1
                ? <> This decision covers more than one document format.</> : null}
              {cluster && severityLine(cluster.severities)
                ? <> The group spans {severityLine(cluster.severities)}.</> : null}
              {' '}The other {matchingCount} carry the same criterion and an actionable proposal; manual,
              blocked and already-decided findings are excluded.
            </span>
            <div>
              <button type="button" className="linklike" aria-expanded={matchingPreviewOpen}
                      onClick={() => setMatchingPreviewOpen((open) => !open)}>Review matching items</button>
              {matchingPreviewOpen && <>
              <ul className="remediation-match-preview">
                {matchingFindings.slice(0, 5).map((item) => (
                  <li key={item.id}><b>{displayText(item.file)}</b><span>{displayText(item.after || item.observed || 'No proposed value recorded')}</span></li>
                ))}
              </ul>
              {matchingCount > 5 && <p className="muted" style={{ margin: '4px 0 0' }}>And {matchingCount - 5} more matching findings.</p>}
              </>}
            </div>
            <div style={{ flexBasis: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
                          padding: '10px 12px', border: '1px solid var(--line,#e2dce4)', borderRadius: 9,
                          background: 'var(--bg,#fff)' }}>
              <span style={{ lineHeight: 1.4 }}>
                <b style={{ display: 'block', color: 'var(--ink)', fontSize: 13 }}>Confident this pattern is right?</b>
                Apply the same decision to this item and {matchingCount} similar finding{matchingCount === 1 ? '' : 's'}
                {' '}across {new Set([f.file, ...matchingFindings.map((x) => x.file)]).size} files.
              </span>
              <button type="button" className="primary" disabled={saving}
                      onClick={() => decideForGroup({ state: 'accepted', value: canEdit ? draftValue : undefined })}
                      style={{ flex: '0 0 auto', fontWeight: 750, padding: '9px 14px' }}>
                {saving ? 'Applying…' : isAutoFix
                  ? `Approve all ${matchingCount + 1} similar fixes`
                  : `Approve & apply to all ${matchingCount + 1}`}
              </button>
            </div>
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
              {onOpenWord && <button className="primary" disabled={saving} onClick={() => onOpenWord(f)}>Open in Word</button>}
              {onRecheck && <button className="ghost" disabled={saving} onClick={() => onRecheck(f)}>Upload &amp; recheck</button>}
              <button className="ghost" disabled={saving} onClick={() => onDecide?.(f, { state: 'assigned' })}>Defer</button>
              {/* Out of scope — this criterion doesn't apply to the document. Resolves the finding and
                  takes it out of the coverage denominator (persisted as an out_of_scope resolution). */}
              <button className="ghost" disabled={saving} onClick={() => onDecide?.(f, { state: 'not_applicable' })}>Not applicable</button>
            </>
          ) : isAutoFix ? (
            /* An auto-applied fix: the change is already written, so the decision is a clear approve or
               a flag that it looks wrong — not an edit-and-apply. "This looks wrong" hands the finding
               back for a person; it does NOT auto-revert the applied change (no backend undo exists —
               see PR body), so it is labelled as a flag, not a "reject & revert". */
            <>
              <button className="primary" disabled={saving} onClick={() => onDecide?.(f, { state: 'accepted' })}>
                {saving ? 'Saving…' : 'Approve & next →'}
              </button>
              <button className="ghost" disabled={saving} onClick={() => onDecide?.(f, { state: 'rejected' })}>This looks wrong</button>
              {onOpenWord && <button className="ghost" disabled={saving} onClick={() => onOpenWord(f)}>Open source document</button>}
              <button className="ghost" disabled={saving} onClick={() => onDecide?.(f, { state: 'not_applicable' })}>Not applicable</button>
            </>
          ) : (
            <>
              <button className="primary" disabled={saving}
                      onClick={() => onDecide?.(f, { state: 'accepted', value: canEdit ? draftValue : undefined })}>
                {saving ? 'Applying…' : edited ? 'Apply edited fix & next →' : 'Apply fix & next →'}
              </button>
              {canEdit && <button className="ghost" disabled={saving} onClick={() => draftRef.current?.focus()}>Edit proposed fix</button>}
              {/* A specific action, not a bare "Reject": declining an AI fix hands the finding to a
                  person (the handoff lane), so the label names that outcome rather than leaving the
                  reviewer to guess what "Reject" does. */}
              <button className="ghost" disabled={saving} onClick={() => onDecide?.(f, { state: 'rejected' })}>Reject to manual</button>
              <button className="ghost" disabled={saving} onClick={() => onDecide?.(f, { state: 'assigned' })}>Defer</button>
              <button className="ghost" disabled={saving} onClick={() => onDecide?.(f, { state: 'not_applicable' })}>Not applicable</button>
              {onOpenWord && <button className="ghost" disabled={saving} onClick={() => onOpenWord(f)}>Open source document</button>}
            </>
          )}
        </div>
        {/* The decision that did NOT save, stated where the reviewer pressed the button. The finding
            stays selected and unresolved behind this — nothing advanced, and nothing was recorded. */}
        {error && (
          <div role="alert"
               style={{ margin: '0 22px 14px', padding: '10px 12px', borderRadius: 8, fontSize: 12.5,
                        border: '1px solid #C0392B', background: '#FDEDEC', color: '#7B241C' }}>
            <b>Not saved.</b> {error.message} This finding is still waiting for your decision — nothing was recorded and you have not moved on.
          </div>
        )}
      </div>
    </div>
  )
}

// Below this the queue and the review panel each get the full width, one at a time. Chosen so the
// review panel keeps a readable measure at 200% zoom rather than at a device size.
const NARROW_Q = '(max-width: 820px)'

// A workspace preference (the reviewer sets it once), so it lives in localStorage keyed globally —
// unlike search/filter state, which is per-scan sessionStorage. Every access is guarded: storage
// can throw (private mode, disabled) and must never take the inbox down with it.
const LS = 'acp.remediate.'
function readLS(k, dflt) { try { const v = localStorage.getItem(LS + k); return v == null ? dflt : v } catch { return dflt } }
function readNum(k, dflt) { const n = parseFloat(readLS(k, '')); return Number.isFinite(n) ? n : dflt }
function writeLS(k, v) { try { localStorage.setItem(LS + k, String(v)) } catch { /* storage unavailable — keep the in-memory value */ } }
function readSession(k, dflt) { try { return sessionStorage.getItem(k) ?? dflt } catch { return dflt } }
function writeSession(k, v) { try { sessionStorage.setItem(k, String(v)) } catch { /* keep in-memory state */ } }
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
  initialSort = 'priority', initialTab = 'needs-review', scanId = null,
  assignees = {}, myEmail = null, onAssign,
  // The per-ITEM board components (R4 fix preview, R7 per-document progress, R10 audit trail)
  // belong beside the selected finding, but this component must not import them: it already owns
  // the hardest state on the page, and three more imports would make it the place every future
  // panel lands. A render prop keeps the composition with the parent, which owns the page.
  //
  // Called with the selected finding, or null when nothing is selected — the callee decides what
  // an empty selection means rather than this component guessing on its behalf.
  renderDetailExtra = null,
}) {
  const [selectedId, setSelectedId] = useState(null)
  const [tab, setTab] = useState(initialTab)
  const [sort, setSort] = useState(initialSort)
  const [search, setSearch] = useState('')
  const filterKey = `acp.remediate.filters.${scanId || 'current'}`
  const [priorityFilter, setPriorityFilter] = useState(() => readSession(`${filterKey}.priority`, 'all'))
  const [formatFilter, setFormatFilter] = useState(() => readSession(`${filterKey}.format`, 'all'))
  useEffect(() => { writeSession(`${filterKey}.priority`, priorityFilter) }, [filterKey, priorityFilter])
  useEffect(() => { writeSession(`${filterKey}.format`, formatFilter) }, [filterKey, formatFilter])
  const [collapsed, setCollapsed] = useState({}) // file -> true when a document group is collapsed
  const [drafts, setDrafts] = useState({}) // finding id -> reviewer-edited proposed value (null until edited)
  const [assignedOnly, setAssignedOnly] = useState(false) // "Assigned to me" filter — files whose assignee is myEmail
  // How the queue groups its rows. BY ISSUE is the default: like findings collapse into one cluster
  // row a reviewer inspects once and decides once, which is the whole point — a flat list of 265
  // findings is a rubber-stamping machine no matter how good each row looks. BY DOCUMENT is the
  // older lens, kept because "what is wrong with THIS file" is a real question too.
  const [group, setGroup] = useState(() => (readLS('group', 'issue') === 'document' ? 'document' : 'issue'))
  useEffect(() => { writeLS('group', group) }, [group])
  const [expandedClusters, setExpandedClusters] = useState({})  // cluster key -> true
  const toggleCluster = (key) => setExpandedClusters((e) => ({ ...e, [key]: !e[key] }))
  const [bulkPreviewOpen, setBulkPreviewOpen] = useState(false)
  const [bulkError, setBulkError] = useState('')

  const [leftW, setLeftW] = useState(() => clamp(readNum('leftW', 33), 28, 40))
  useEffect(() => { writeLS('leftW', leftW) }, [leftW])

  // ── Narrow viewports: two panels side by side stop being two panels and become two half-panels.
  // Below the breakpoint the workspace shows ONE of them at a time — the queue, or the finding with
  // a way back to the queue (PRD §12). matchMedia is absent in jsdom and in older engines, so the
  // guard is a capability check, not a version check, and its failure mode is the desktop layout.
  const [narrow, setNarrow] = useState(() => {
    try { return !!window.matchMedia?.(NARROW_Q).matches } catch { return false }
  })
  useEffect(() => {
    let mq
    try { mq = window.matchMedia?.(NARROW_Q) } catch { return undefined }
    if (!mq) return undefined
    const on = (e) => setNarrow(e.matches)
    // addListener is the pre-2019 spelling; Safari only grew addEventListener here in 14.
    if (mq.addEventListener) { mq.addEventListener('change', on); return () => mq.removeEventListener('change', on) }
    if (mq.addListener) { mq.addListener(on); return () => mq.removeListener(on) }
    return undefined
  }, [])
  // Which of the two the narrow layout is showing. Selecting a finding moves to it; "Back to queue"
  // returns. Ignored entirely at desktop widths, where both panels are on screen at once.
  const [narrowPane, setNarrowPane] = useState('queue')

  const rowRef = useRef(null)   // the .rinbox flex row — the frame for horizontal (column) resizes
  // Drag: translate a pointer position into a percentage of the relevant frame. Guarded on a real
  // measured size, so jsdom's zero-size rects leave the value untouched (keyboard drives the tests).
  const dragLeft = (x) => { const r = rowRef.current?.getBoundingClientRect(); if (r?.width) setLeftW(clamp(((x - r.left) / r.width) * 100, 28, 40)) }

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
      (priorityFilter === 'all' || String(f.severity || 'unrated').toLowerCase() === priorityFilter) &&
      (formatFilter === 'all' || fmtOf(f.file) === formatFilter) &&
      (!q || rowModel(f, decisions).issue.toLowerCase().includes(q) || String(f.file).toLowerCase().includes(q)))
    return sortQueue(filtered, sort)
  }, [queue, tab, sort, search, decisions, assignedOnly, assignees, myEmail, priorityFilter, formatFilter]) // eslint-disable-line react-hooks/exhaustive-deps

  // Bold bulk work is scoped to what the reviewer can currently see and explain. It never reaches
  // manual, blocked, handed-off or already-decided findings, and every target keeps its own proposal.
  const visibleBulkTargets = useMemo(() => visible.filter((f) => {
    const key = laneOf(f).key
    return !isResolved(f, decisions) && (key === 'apply' || key === 'review') && f.after != null && f.after !== ''
  }), [visible, decisions])

  // Keep a valid selection: default to the first unresolved visible row.
  useEffect(() => {
    if (selectedId != null && visible.some((f) => f.id === selectedId)) return
    const firstOpen = visible.find((f) => !isResolved(f, decisions)) || visible[0]
    setSelectedId(firstOpen ? firstOpen.id : null)
  }, [visible, selectedId, decisions])

  // A decision being written, and the last one refused. Both are keyed by finding id so the pane can
  // only ever show a busy or failed state against the finding it actually belongs to.
  const [savingId, setSavingId] = useState(null)
  const [saveError, setSaveError] = useState(null)
  const [savedMessage, setSavedMessage] = useState('')
  const savedTimerRef = useRef(null)
  useEffect(() => () => clearTimeout(savedTimerRef.current), [])
  // Findings the parent has optimistically removed from `queue` while their write is in flight. Kept
  // only until the write settles, so the review pane never blanks mid-decision.
  const heldRef = useRef(new Map())

  const selected = queue.find((f) => f.id === selectedId) || heldRef.current.get(selectedId) || null
  const reviewHeadingRef = useRef(null)
  const focusReviewRef = useRef(false)
  // One selection entry point for both layouts: at desktop widths this is just setSelectedId; when
  // only one panel fits, picking a finding is also the navigation TO it.
  const selectRow = (id) => { focusReviewRef.current = true; setSelectedId(id); setNarrowPane('detail') }
  useEffect(() => {
    if (!focusReviewRef.current) return
    focusReviewRef.current = false
    reviewHeadingRef.current?.focus()
  }, [selectedId, narrowPane])
  const groups = useMemo(() => groupByDocument(visible), [visible])
  const clusters = useMemo(() => clusterRows(visible, decisions), [visible, decisions])

  // The finding a cluster row SHOWS. Normally its representative (the first undecided member), but
  // the selected member when the selection is inside it — so a decision made from inside a cluster,
  // or an auto-advance into one, is always visible without forcing the group open.
  const shownOf = (row) => row.items.find((f) => f.id === selectedId) || row.items.find((f) => f.id === row.representativeId) || row.items[0]

  // Navigation units, in display order: what Up/Down step through and what "N of M" counts. A
  // collapsed cluster is ONE unit (the finding it shows); an expanded one contributes its members.
  // Grouping by document leaves every finding its own unit, exactly as before.
  const navFindings = useMemo(() => {
    if (group !== 'issue') return visible
    const out = []
    for (const row of clusters) {
      if (row.type === 'single') { out.push(row.finding); continue }
      if (expandedClusters[row.key]) out.push(...row.items)
      else out.push(shownOf(row))
    }
    return out
  }, [group, clusters, expandedClusters, visible, selectedId]) // eslint-disable-line react-hooks/exhaustive-deps
  // Moving off a failed finding clears its error — the message belongs to that decision, not the page.
  useEffect(() => { setSaveError((e) => (e && e.id !== selectedId ? null : e)) }, [selectedId])

  // W8 — every OTHER unresolved queued finding that shares this one's rule/SC. Drives the
  // "apply to all matching" count and the batch action. Restricted to the actionable approve/apply
  // lanes: a batch decision must not silently sweep in a finding a person already rejected (handoff),
  // one that needs a manual re-author, or a blocked one.
  // W8 — the batch. Its scope is the SELECTED FINDING'S CLUSTER, not "every finding sharing this
  // criterion": what the reviewer sees grouped in the queue is exactly what one decision reaches,
  // and there is no second, invisible notion of "matching". That is stricter than the rule it
  // replaces, which spanned formats — the same criterion is remediated differently in a .docx and a
  // .pdf and the evidence differs, so the run's own policy (PRD Tier C) requires format to match.
  //
  // batchTargetsOf applies the safety filter: unresolved, and in an actionable lane. A manual,
  // blocked, handed-off or already-decided finding is never swept into a batch.
  const selectedCluster = useMemo(
    () => (selected ? clusterOfFinding(clusters, selected.id) : null), [clusters, selected])
  const matchingOf = (f) => {
    const row = clusterOfFinding(clusters, f?.id)
    return batchTargetsOf(row, decisions).filter((x) => x.id !== f?.id)
  }
  const matchingFindings = selected ? matchingOf(selected) : []
  const queueComplete = queue.length > 0 && queue.every((f) => isResolved(f, decisions))
  const emptyReviewState = queue.length === 0 || queueComplete
    ? <div><b style={{ color: 'var(--ink)' }}>All review items are complete.</b><br />{prog.resolved} resolved · {counts.completed || 0} completed</div>
    : <p style={{ marginTop: 8 }}>No items are available in {WORKFLOW_LABELS[tab]}. Choose another status from the inbox.</p>

  // Act on a finding, then auto-advance to the next unresolved one — the behaviour that makes the
  // queue feel like a controlled worklist rather than a scroll through an audit report.
  //
  // ADVANCING IS CONDITIONAL ON THE WRITE SUCCEEDING. This used to call onDecide and move on in the
  // same breath: the decision was fire-and-forget, so a server refusal advanced the reviewer to the
  // next finding anyway and the only trace was a banner rendered OUTSIDE this component, above the
  // whole inbox. The reviewer saw a decision they had made land on a finding that had scrolled past.
  // Now the save is awaited — on failure the item stays selected, the error is stated inline next to
  // the buttons that failed, and nothing advances.
  async function act(f, decision) {
    if (!f || savingId != null) return
    // The parent removes the row from `queue` optimistically and puts it back only if the write
    // fails, so hold our own reference to keep the pane rendering THIS finding while it is in flight.
    heldRef.current.set(f.id, f)
    setSavingId(f.id)
    setSaveError(null)
    let ok = true
    try {
      // `onDecide` returns a promise once the parent has a write to report on; older call sites
      // return undefined, which awaits to undefined and keeps the previous advance-always behaviour.
      await onDecide?.(f, decision)
    } catch (e) {
      ok = false
      setSaveError({ id: f.id, message: e?.message || String(e || 'The server did not accept it.') })
    }
    setSavingId(null)
    if (!ok) { setSelectedId(f.id); return }   // stay put — the decision was NOT recorded
    heldRef.current.delete(f.id)
    // `visible` is the list as it was when this handler was created, i.e. BEFORE the parent removed
    // the decided row — which is exactly the ordering the "next" finding should be taken from.
    const nextDecisions = { ...decisions, [f.id]: decision }
    setSavedMessage(`${rowModel(f, decisions).issue} saved. Moving to the next finding.`)
    clearTimeout(savedTimerRef.current)
    savedTimerRef.current = setTimeout(() => setSavedMessage(''), 2400)
    focusReviewRef.current = true
    setSelectedId(nextUnresolvedId(visible, f.id, nextDecisions))
  }

  // W8 — apply one decision to the current finding AND every matching one, in a single click. Each
  // target routes through the same onDecide as an individual action, so approvals still re-validate
  // and rejections still hand off; then advance past everything just decided.
  //
  // Partial failure is reported rather than hidden (PRD §6): the writes are awaited together, and if
  // some are refused the batch says how many landed and how many are still unresolved, and the
  // selection stays on the first finding that failed instead of advancing past the whole cluster.
  async function applyToMatching(f, decision) {
    if (!f || savingId != null) return
    const targets = [f, ...matchingOf(f)]
    targets.forEach((t) => heldRef.current.set(t.id, t))
    setSavingId(f.id)
    setSaveError(null)
    const results = await Promise.allSettled(targets.map((t) => onDecide?.(t, decision)))
    setSavingId(null)
    const failed = targets.filter((_, i) => results[i].status === 'rejected')
    const nextDecisions = { ...decisions }
    targets.forEach((t, i) => { if (results[i].status === 'fulfilled') { nextDecisions[t.id] = decision; heldRef.current.delete(t.id) } })
    if (failed.length) {
      setSaveError({ id: failed[0].id, batch: { saved: targets.length - failed.length, failed: failed.length },
                     message: `${targets.length - failed.length} of ${targets.length} saved. ${failed.length} could not be saved and ${failed.length === 1 ? 'is' : 'are'} still unresolved.` })
      setSelectedId(failed[0].id)
      return
    }
    setSavedMessage(`${targets.length} matching findings saved. Moving to the next finding.`)
    clearTimeout(savedTimerRef.current)
    savedTimerRef.current = setTimeout(() => setSavedMessage(''), 2400)
    focusReviewRef.current = true
    setSelectedId(nextUnresolvedId(visible, f.id, nextDecisions))
  }

  async function applyVisibleBulk() {
    if (savingId != null || visibleBulkTargets.length === 0) return
    setSavingId('visible-bulk'); setBulkError('')
    const results = await Promise.allSettled(visibleBulkTargets.map((f) =>
      onDecide?.(f, { state: 'accepted', value: f.after })))
    const failed = visibleBulkTargets.filter((_, i) => results[i].status === 'rejected')
    setSavingId(null)
    if (failed.length) {
      setBulkError(`${visibleBulkTargets.length - failed.length} of ${visibleBulkTargets.length} fixes saved. ${failed.length} still need attention.`)
      setSelectedId(failed[0].id)
      return
    }
    setBulkPreviewOpen(false)
    setSavedMessage(`${visibleBulkTargets.length} visible fixes approved and applied.`)
    clearTimeout(savedTimerRef.current)
    savedTimerRef.current = setTimeout(() => setSavedMessage(''), 2400)
  }

  const visibleBulkFiles = new Set(visibleBulkTargets.map((f) => f.file)).size
  const visibleBulkCriteria = new Set(visibleBulkTargets.map(scKeyOf).filter(Boolean)).size

  // Explicit linear navigation through the visible queue — Previous / Next step the SELECTION without
  // acting, so a reviewer can look before deciding and always sees their place ("N of M").
  const visIds = navFindings.map((f) => f.id)
  const curIdx = visIds.indexOf(selectedId)
  const position = curIdx >= 0 ? curIdx + 1 : 0
  const goPrev = () => { if (curIdx > 0) setSelectedId(visIds[curIdx - 1]) }
  const goNext = () => { if (curIdx >= 0 && curIdx < visIds.length - 1) setSelectedId(visIds[curIdx + 1]) }

  // ── Keyboard navigation + screen-reader support for the queue ──
  // The queue is operable end to end without a mouse: one Tab lands on the selected row (roving
  // tabindex on QueueRow), then Up/Down (or j/k) step the selection and Home/End jump to the ends. A
  // polite live region announces the moved-to finding and its N-of-M place — and the SAME announcement
  // fires on the auto-advance after a decision, so a screen-reader user always knows where the
  // workspace just went. (An accessibility tool should itself be exemplary here.)
  const listRef = useRef(null)   // the queue's scroll container; catches key events bubbling from the rows
  const kbNavRef = useRef(false) // set when the selection moved by keyboard, so focus follows it
  const onQueueKey = (e) => {
    const k = e.key
    if (k === 'ArrowDown' || k === 'j') { e.preventDefault(); kbNavRef.current = true; goNext() }
    else if (k === 'ArrowUp' || k === 'k') { e.preventDefault(); kbNavRef.current = true; goPrev() }
    else if (k === 'Home') { e.preventDefault(); if (visIds.length) { kbNavRef.current = true; setSelectedId(visIds[0]) } }
    else if (k === 'End') { e.preventDefault(); if (visIds.length) { kbNavRef.current = true; setSelectedId(visIds[visIds.length - 1]) } }
  }
  // Move focus to the newly-selected row ONLY when the change came from the keyboard, so a mouse click
  // (or the auto-advance after a decision) never yanks focus out from under the reviewer.
  useEffect(() => {
    if (!kbNavRef.current) return
    kbNavRef.current = false
    listRef.current?.querySelector('[aria-current="true"]')?.focus()
  }, [selectedId])
  const announce = visIds.length === 0
    ? 'No findings in this view.'
    : (selected ? `Finding ${position} of ${visIds.length}: ${rowModel(selected, decisions).issue}, in ${selected.file}.` : '')

  // The two workspace panes, defined once and placed differently per layout (side by side, stacked,
  // or guided-only). The layout toggle sits on the guided header — the pane that is always shown.
  const guidedHeader = (
    <div style={{ flex: '0 0 auto', padding: '8px 12px', borderBottom: '1px solid var(--line,#e2dce4)',
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
        {narrow && (
          <button type="button" onClick={() => setNarrowPane('queue')}
                  style={{ fontSize: 11.5, fontWeight: 600, padding: '4px 10px', borderRadius: 8, cursor: 'pointer',
                           border: '1px solid var(--line,#e2dce4)', background: 'var(--bg,#fff)' }}>
            &larr; Back to queue
          </button>
        )}
        <span style={{ fontSize: 13, fontWeight: 700 }}>Guided remediation</span>
      </span>
    </div>
  )
  const guidedBody = (
    <>
      <DetailPane f={selected} decisions={decisions} onDecide={act} onOpenWord={onOpenWord} onRecheck={onRecheck}
                  headingRef={reviewHeadingRef}
                  saving={savingId != null && savingId === selected?.id}
                  error={saveError && selected && saveError.id === selected.id ? saveError : null}
                  matchingFindings={matchingFindings} onApplyToMatching={applyToMatching} cluster={selectedCluster?.type === 'cluster' ? selectedCluster : null}
                  draft={selected ? (drafts[selected.id] ?? null) : null}
                  onDraftChange={(v) => selected && setDrafts((d) => ({ ...d, [selected.id]: v }))}
                  detailExtra={renderDetailExtra ? renderDetailExtra(selected) : null}
                  emptyState={emptyReviewState} />
    </>
  )
  return (
    <div className="rinbox-wrap">
      {/* Screen-reader announcer: the selected finding and its place in the queue, updated on every
          selection change — manual, keyboard, or the auto-advance after a decision. Visually hidden. */}
      <div aria-live="polite" role="status"
           style={{ position: 'absolute', width: 1, height: 1, padding: 0, margin: -1, overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap', border: 0 }}>
        {announce}
      </div>
      {savedMessage && <div className="remediation-saved" role="status" aria-live="polite">✓ {savedMessage}</div>}
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
      <div className="rinbox" data-layout="two-column" data-narrow={narrow ? narrowPane : undefined} ref={rowRef} style={{ display: 'flex', gap: 0, border: '1px solid var(--line,#e2dce4)', borderRadius: '0 0 12px 12px', overflow: 'hidden', minHeight: 480 }}>
      {/* ── Left: the work queue — find and select the next finding (resizable) ── */}
      <div className="rinbox-queuepane" hidden={narrow && narrowPane !== 'queue'}
           style={{ ...(narrow ? { flex: '1 1 auto', maxWidth: 'none' } : { flex: `0 0 ${leftW}%`, maxWidth: `${leftW}%` }),
                    display: narrow && narrowPane !== 'queue' ? 'none' : 'flex', flexDirection: 'column', minHeight: 480 }}>
        <div style={{ flex: '0 0 auto', padding: '10px 12px', borderBottom: '1px solid var(--line,#e2dce4)' }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>Remediation Inbox</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input type="search" value={search} onChange={(e) => setSearch(e.target.value)}
                   placeholder="Search documents" aria-label="Search documents"
                   style={{ flex: '1 1 auto', minWidth: 0, fontSize: 13, padding: '6px 10px', borderRadius: 8, border: '1px solid var(--line,#e2dce4)' }} />
            <select value={group} onChange={(e) => setGroup(e.target.value)} aria-label="Group findings" title="Group findings"
                    style={{ flex: '0 0 auto', fontSize: 11.5, padding: '5px 6px', borderRadius: 6, border: '1px solid var(--line,#e2dce4)' }}>
              <option value="issue">By issue</option>
              <option value="document">By document</option>
            </select>
            <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort findings" title="Sort findings"
                    style={{ flex: '0 0 auto', fontSize: 11.5, padding: '5px 6px', borderRadius: 6, border: '1px solid var(--line,#e2dce4)' }}>
              {SORTS.map((s) => <option key={s} value={s}>{SORT_LABEL[s]}</option>)}
            </select>
          </div>
          <div className="remediation-filters" aria-label="Filter remediation inbox">
            <select value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)} aria-label="Filter by priority">
              <option value="all">All priorities</option>
              <option value="critical">Critical</option><option value="serious">Serious</option>
              <option value="moderate">Moderate</option><option value="minor">Minor</option><option value="unrated">Unrated</option>
            </select>
            <select value={formatFilter} onChange={(e) => setFormatFilter(e.target.value)} aria-label="Filter by file format">
              <option value="all">All formats</option><option value="docx">DOCX</option><option value="pdf">PDF</option>
              <option value="pptx">PPTX</option><option value="xlsx">XLSX</option>
            </select>
            {(priorityFilter !== 'all' || formatFilter !== 'all') && (
              <button className="linklike" onClick={() => { setPriorityFilter('all'); setFormatFilter('all') }}>Clear filters</button>
            )}
            <details className="remediation-shortcuts">
              <summary>Keyboard help</summary>
              <span>↑/↓ or J/K: move · Home/End: first/last · Enter: open selected item</span>
            </details>
          </div>
          {visibleBulkTargets.length > 1 && (
            <button type="button" className="ghost" aria-expanded={bulkPreviewOpen}
                    onClick={() => { setBulkPreviewOpen((open) => !open); setBulkError('') }}
                    style={{ marginTop: 8, fontWeight: 700 }}>
              Bulk actions · {visibleBulkTargets.length} visible fixes
            </button>
          )}
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
        <div ref={listRef} onKeyDown={onQueueKey} aria-label="Findings — use Up and Down arrow keys to move between them"
             style={{ flex: '1 1 auto', overflowY: 'auto' }}>
          {visible.length === 0 ? (
            <div className="muted" style={{ padding: 16, fontSize: 13 }}>
              {queue.length === 0 || queueComplete
                ? <><b style={{ color: 'var(--ink)' }}>All review items are complete.</b><p style={{ margin: '6px 0 0' }}>{prog.resolved} resolved · {counts.completed || 0} completed</p></>
                : search.trim()
                ? <>No findings match “{displayText(search.trim())}”. <button className="linklike" onClick={() => setSearch('')}>Clear search</button></>
                : priorityFilter !== 'all' || formatFilter !== 'all'
                ? <>No findings match these filters. <button className="linklike" onClick={() => { setPriorityFilter('all'); setFormatFilter('all') }}>Clear filters</button></>
                : assignedOnly
                ? <>Nothing in this view is assigned to you. <button className="linklike" onClick={() => setAssignedOnly(false)}>Show all</button></>
                : <>No items in {WORKFLOW_LABELS[tab]}. {tab !== 'needs-review' && <button className="linklike" onClick={() => setTab('needs-review')}>Review AI suggestions</button>}</>}
            </div>
          ) : group === 'issue' ? clusters.map((row) => (
            row.type === 'single'
              ? <QueueRow key={row.key} f={row.finding} decisions={decisions}
                          selected={row.finding.id === selectedId} onSelect={selectRow} showFile />
              : <ClusterRow key={row.key} row={row} shown={shownOf(row)} decisions={decisions}
                            selectedId={selectedId} onSelect={selectRow}
                            expanded={!!expandedClusters[row.key]} onToggle={toggleCluster} />
          )) : groups.map((g) => (
            // A document with a SINGLE finding needs no expandable group header — the row itself
            // names the file. Only multi-finding documents get the collapsible 📄 header, so the file
            // is stated once either way.
            g.items.length === 1 ? (
              <QueueRow key={g.items[0].id} f={g.items[0]} decisions={decisions}
                        selected={g.items[0].id === selectedId} onSelect={selectRow} showFile />
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
                  <QueueRow key={f.id} f={f} decisions={decisions} selected={f.id === selectedId} onSelect={selectRow} showFile={false} />
                ))}
              </div>
            )
          ))}
        </div>
      </div>

      {/* Divider between the inbox and the workspace — present whenever both are on screen. */}
      {!narrow && (
        <Divider orientation="vertical" label="Resize the inbox" value={leftW} min={28} max={40}
                 onDrag={dragLeft} onNudge={(d) => setLeftW((w) => clamp(w + d * 2, 28, 40))} />
      )}

      {/* ── The workspace: the review canvas, plus the document preview when it is open ──
          ONE tree for all three states, rather than a branch per layout. The guided column keeps the
          same position in the element tree whether the preview is closed, beside it, or below it, so
          React reconciles it instead of remounting — which is what lets the reviewer open the full
          preview mid-decision and come back to their scroll position and their unsaved edit. */}
      <div className="rinbox-workspace" hidden={narrow && narrowPane !== 'detail'}
           style={{ flex: '1 1 auto', minWidth: 0, minHeight: 480,
                    display: narrow && narrowPane !== 'detail' ? 'none' : 'flex',
                    flexDirection: 'row' }}>
        <div style={{ flex: '1 1 auto', minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          {guidedHeader}
          <div className="rinbox-guided-scroll"
               style={{ flex: '1 1 auto', minHeight: 0, overflowY: 'auto', overflowX: 'hidden' }}>
            {guidedBody}
          </div>
        </div>

      </div>
      </div>
      {bulkPreviewOpen && visibleBulkTargets.length > 1 && (
        <div role="region" aria-label="Bulk approval summary"
             style={{ position: 'sticky', bottom: 0, zIndex: 5, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 14,
                      padding: '12px 16px', border: '1px solid var(--accent,#3b6fd6)', background: 'var(--bg,#fff)', boxShadow: '0 -5px 18px rgba(31,43,58,.14)' }}>
          <span style={{ fontSize: 13, lineHeight: 1.45 }}>
            <b>Apply every actionable fix in this view</b>
            <span style={{ display: 'block' }}>{visibleBulkTargets.length} fixes · {visibleBulkFiles} file{visibleBulkFiles === 1 ? '' : 's'} · {visibleBulkCriteria} WCAG {visibleBulkCriteria === 1 ? 'criterion' : 'criteria'}</span>
            <span className="muted" style={{ display: 'block' }}>Each file keeps its own proposal. Manual, blocked, handed-off, and decided work is excluded.</span>
            {bulkError && <span role="alert" style={{ display: 'block', color: 'var(--error-fg-strong,#9f221c)', marginTop: 3 }}>{bulkError}</span>}
          </span>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flex: '0 0 auto' }}>
            <button type="button" className="ghost" onClick={() => setBulkPreviewOpen(false)}>Cancel</button>
            <button type="button" className="primary" disabled={savingId != null} onClick={applyVisibleBulk}
                    style={{ fontWeight: 750, padding: '10px 16px' }}>
              {savingId === 'visible-bulk' ? 'Applying visible fixes…' : `Approve & apply all ${visibleBulkTargets.length}`}
            </button>
          </div>
        </div>
      )}
      {/* Sticky workflow guide (Show → Review → Verify) + Previous / N of M / Next navigation. */}
      <WorkspaceFooter position={position} total={visIds.length} onPrev={goPrev} onNext={goNext}
                       activeStep={selected ? workflowStepIndex(selected, decisions) : null} />
    </div>
  )
}

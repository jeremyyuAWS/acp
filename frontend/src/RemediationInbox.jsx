import { useMemo, useState, useEffect } from 'react'
import {
  rowModel, laneOf, sortQueue, groupByDocument, nextUnresolvedId, progress, railColorOf,
  matchesWorkflow, workflowCounts, workflowStepIndex, isResolved, WORKFLOW_TABS, WORKFLOW_LABELS, SORTS,
} from './remediationInboxModel.js'
import { fixSteps, appName } from './remediationGuide.js'
import { scOf } from './fixSummary.js'
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
        {/* The lane's status is the badge below — the full sentence (r.did) is stated once, in the
            workspace detail, not repeated on every row. */}
        <span style={{ display: 'flex', gap: 8, marginTop: 4, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: r.lane.color,
                         border: `1px solid ${r.lane.color}`, borderRadius: 20, padding: '1px 8px' }}>
            {r.lane.label}
          </span>
          {r.effort !== '—' && <span className="muted" style={{ fontSize: 11 }}>{r.effort}</span>}
          {r.severity && <span className={`revcard-sev sev-${String(r.severity).toLowerCase()}`} style={{ fontSize: 10 }}>{r.severity}</span>}
          {r.resolved && <span className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>✓ resolved</span>}
        </span>
      </span>
    </button>
  )
}

function BeforeAfter({ f }) {
  const [view, setView] = useState('after') // 'before' | 'after'
  const hasBoth = f.before != null && f.after != null
  return (
    <div>
      {hasBoth && (
        <div role="tablist" aria-label="Before and after" style={{ display: 'inline-flex', border: '1px solid var(--line,#e2dce4)', borderRadius: 8, overflow: 'hidden', marginBottom: 10 }}>
          {['before', 'after'].map((v) => (
            <button key={v} role="tab" aria-selected={view === v} onClick={() => setView(v)}
                    style={{ fontSize: 12, fontWeight: 600, padding: '4px 14px', cursor: 'pointer', border: 'none',
                             background: view === v ? 'var(--ink)' : 'transparent', color: view === v ? '#fff' : 'var(--ink)' }}>
              {v === 'before' ? 'Before' : 'After'}
            </button>
          ))}
        </div>
      )}
      <div style={{ border: '1px solid var(--line,#e2dce4)', borderRadius: 8, padding: 12, fontSize: 13 }}>
        {view === 'before'
          ? <div><span className="difftag">before</span> {String(f.before ?? '—')}</div>
          : <div><span className="difftag">after</span> {String(f.after ?? f.before ?? '—')}</div>}
      </div>
      {f.evidence && (
        <div className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>{f.evidence}</div>
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
    </div>
  )
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
  const resolved = isResolved(f, decisions)
  const eyebrow = isHandoff ? 'Needs manual handling' : lane.key === 'manual' ? 'Manual remediation' : 'Review'
  // A drafted AI value the reviewer can adjust before applying. `draft` falls back to the finding's
  // proposed value until the reviewer types; `edited` flips the primary action to "Save edited fix".
  const canEdit = !isManual && f.after != null && f.after !== ''
  const draftValue = draft ?? (f.after ?? '')
  const edited = canEdit && draftValue !== (f.after ?? '')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ flex: '1 1 auto', overflowY: 'auto', padding: '18px 22px' }}>
        {/* 1 · What do I need to do? */}
        <p className="muted" style={{ fontSize: 11.5, letterSpacing: '.08em', textTransform: 'uppercase', margin: 0 }}>
          {eyebrow}
        </p>
        <h3 style={{ margin: '4px 0 6px', fontSize: 19 }}>{r.issue}</h3>
        <p style={{ fontSize: 14, color: 'var(--ink)', margin: '0 0 4px' }}>{lane.didLine}.</p>
        <Meta row={{ ...r, wcag: (f.rule_id || f.ruleId || '') }} />

        {/* 2 · Evidence — see the finding in the document (the folded-in preview). Adaptive: a boxed
            page region for a visible finding, an honest note for a structure/metadata one. */}
        <div style={{ marginTop: 18 }}>
          <p className="muted" style={{ fontSize: 11.5, letterSpacing: '.08em', textTransform: 'uppercase', margin: '0 0 8px' }}>
            Evidence
          </p>
          <RemediationPreview finding={f} scanId={scanId} embedded />
        </div>

        {/* 3 · What changed? (or, for manual, how to change it) */}
        <div style={{ marginTop: 18 }}>
          <p className="muted" style={{ fontSize: 11.5, letterSpacing: '.08em', textTransform: 'uppercase', margin: '0 0 8px' }}>
            {isManual ? 'How to fix it' : 'What changed'}
          </p>
          {isManual
            ? <ManualSteps f={f} />
            : canEdit
              ? (
                <>
                  <RemediationTransform finding={f} decisions={decisions} />  {/* Found → Proposed → Verified */}
                  {/* Editable draft — the reviewer adjusts the exact text ACP will write, then applies
                      their version. Empties reset to the AI's proposal (placeholder), never a blank fix. */}
                  <div style={{ marginTop: 10 }}>
                    <label className="muted" htmlFor="rem-draft" style={{ fontSize: 11.5, letterSpacing: '.08em', textTransform: 'uppercase', display: 'block', margin: '0 0 6px' }}>
                      Edit before applying
                    </label>
                    <textarea id="rem-draft" value={draftValue} onChange={(e) => onDraftChange?.(e.target.value)}
                              aria-label="Edit the proposed fix" rows={2}
                              style={{ width: '100%', fontSize: 13.5, padding: '8px 10px', borderRadius: 8,
                                       border: '1px solid var(--line,#e2dce4)', fontFamily: 'inherit', resize: 'vertical' }} />
                    {edited && <p className="muted" style={{ fontSize: 11.5, margin: '4px 0 0' }}>Edited — “Save edited fix” writes your version instead of the AI’s.</p>}
                  </div>
                </>
              )
              : <BeforeAfter f={f} />}
        </div>

        {/* Collapsed context — kept out of the default view (spec: two collapsed sections). */}
        {(f.rationale || f.whyMatters) && (
          <details style={{ marginTop: 16 }}>
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

      {/* 3 · Sticky action bar */}
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
            </>
          ) : (
            <>
              <button className="primary" onClick={() => onDecide?.(f, { state: 'accepted', value: canEdit ? draftValue : undefined })}>{edited ? 'Save edited fix' : lane.action}</button>
              {/* A specific action, not a bare "Reject": declining an AI fix hands the finding to a
                  person (the handoff lane), so the label names that outcome rather than leaving the
                  reviewer to guess what "Reject" does. */}
              <button className="ghost" onClick={() => onDecide?.(f, { state: 'rejected' })}>Reject &amp; handle manually</button>
              <button className="ghost" onClick={() => onDecide?.(f, { state: 'assigned' })}>Defer</button>
              {onOpenWord && <button className="ghost" onClick={() => onOpenWord(f)}>Open in Word</button>}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export default function RemediationInbox({
  queue = [], decisions = {}, onDecide, onOpenWord, onRecheck,
  initialSort = 'priority', initialTab = 'inbox', scanId = null,
}) {
  const [selectedId, setSelectedId] = useState(null)
  const [tab, setTab] = useState(initialTab)
  const [sort, setSort] = useState(initialSort)
  const [search, setSearch] = useState('')
  const [collapsed, setCollapsed] = useState({}) // file -> true when a document group is collapsed
  const [drafts, setDrafts] = useState({}) // finding id -> reviewer-edited proposed value (null until edited)

  const counts = useMemo(() => workflowCounts(queue, decisions), [queue, decisions])
  const prog = useMemo(() => progress(queue, decisions), [queue, decisions])

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    const filtered = queue.filter((f) => matchesWorkflow(f, tab, decisions) &&
      (!q || rowModel(f, decisions).issue.toLowerCase().includes(q) || String(f.file).toLowerCase().includes(q)))
    return sortQueue(filtered, sort)
  }, [queue, tab, sort, search, decisions])

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

  return (
    <div className="rinbox-wrap">
      {/* Persistent progress bar — the selected document's remediation progress + ETA, above the panes. */}
      <WorkspaceProgress queue={queue} decisions={decisions} selected={selected} />
      <div className="rinbox" style={{ display: 'flex', gap: 0, border: '1px solid var(--line,#e2dce4)', borderRadius: 12, overflow: 'hidden', minHeight: 480 }}>
      {/* ── Left: the work queue (35%) — find and select the next finding ── */}
      <div style={{ flex: '0 0 35%', maxWidth: '35%', borderRight: '1px solid var(--line,#e2dce4)', display: 'flex', flexDirection: 'column', minHeight: 480 }}>
        <div style={{ flex: '0 0 auto', padding: '10px 12px', borderBottom: '1px solid var(--line,#e2dce4)' }}>
          {/* Compact toolbar — search + sort on ONE row (was three stacked rows: search, tabs, sort+count). */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input type="search" value={search} onChange={(e) => setSearch(e.target.value)}
                   placeholder="Search findings…" aria-label="Search findings"
                   style={{ flex: '1 1 auto', minWidth: 0, fontSize: 13, padding: '6px 10px', borderRadius: 8, border: '1px solid var(--line,#e2dce4)' }} />
            <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort findings" title="Sort findings"
                    style={{ flex: '0 0 auto', fontSize: 11.5, padding: '5px 6px', borderRadius: 6, border: '1px solid var(--line,#e2dce4)' }}>
              {SORTS.map((s) => <option key={s} value={s}>{SORT_LABEL[s]}</option>)}
            </select>
          </div>
          {/* Status filter (pipeline stage) with counts + the single resolved summary, one row. */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8, alignItems: 'center' }}>
            {WORKFLOW_TABS.map((t) => (
              <button key={t} type="button" aria-pressed={tab === t} onClick={() => setTab(t)}
                      style={{ fontSize: 11.5, padding: '2px 9px', borderRadius: 20, cursor: 'pointer',
                               border: `1px solid ${tab === t ? 'var(--ink)' : 'var(--line,#e2dce4)'}`,
                               background: tab === t ? 'var(--ink)' : 'transparent', color: tab === t ? '#fff' : 'var(--ink)',
                               fontWeight: tab === t ? 700 : 500 }}>
                {WORKFLOW_LABELS[t]} {counts[t] > 0 ? counts[t] : ''}
              </button>
            ))}
            <span className="muted" style={{ marginLeft: 'auto', fontSize: 11.5, fontWeight: 600 }}>{prog.resolved} of {prog.total} resolved</span>
          </div>
        </div>
        <div style={{ flex: '1 1 auto', overflowY: 'auto' }}>
          {visible.length === 0 ? (
            <p className="muted" style={{ padding: 16, fontSize: 13 }}>Nothing here. {tab !== 'inbox' && <button className="linklike" onClick={() => setTab('inbox')}>Back to Inbox</button>}</p>
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

      {/* ── Right: the remediation workspace (65%) — one scrolling column that stacks
           Problem → Evidence → How to fix → Decision, with the document preview folded into the
           Evidence section rather than living as a separate, often-empty third pane. ── */}
      <div style={{ flex: '1 1 65%', minWidth: 0 }}>
        <DetailPane f={selected} decisions={decisions} onDecide={act} onOpenWord={onOpenWord} onRecheck={onRecheck}
                    matchingCount={matchingCount} onApplyToMatching={applyToMatching}
                    scanId={selected?.scanId || scanId}
                    draft={selected ? (drafts[selected.id] ?? null) : null}
                    onDraftChange={(v) => selected && setDrafts((d) => ({ ...d, [selected.id]: v }))} />
      </div>
      </div>
      {/* Sticky workflow guide (Show → Review → Verify) + Previous / N of M / Next navigation. */}
      <WorkspaceFooter position={position} total={visIds.length} onPrev={goPrev} onNext={goNext}
                       activeStep={selected ? workflowStepIndex(selected, decisions) : null} />
    </div>
  )
}

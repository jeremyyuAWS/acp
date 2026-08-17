import { useMemo, useState, useEffect } from 'react'
import {
  rowModel, laneOf, sortQueue, groupByDocument, nextUnresolvedId, progress,
  matchesTab, tabCounts, isResolved, TABS, SORTS,
} from './remediationInboxModel.js'
import { fixSteps, appName } from './remediationGuide.js'

// Master/detail Remediation inbox. Remediation is queue work — select an item, understand it, act,
// move to the next — so the layout is an email-style split: a 38% work queue on the left, a 62%
// remediation workspace on the right. Selecting a row NEVER expands it; it populates the detail
// pane. Acting on a finding auto-advances to the next unresolved one, which is what makes the whole
// thing feel fast. All derivation lives in remediationInboxModel.js; this file is presentation.

const SORT_LABEL = { priority: 'Priority', document: 'Document', newest: 'Newest', fastest: 'Fastest to resolve' }
const TAB_LABEL = { all: 'All', 'auto-fixed': 'Auto-fixed', manual: 'Manual', blocked: 'Blocked', resolved: 'Resolved' }
const fmtOf = (file) => String(file || '').split('.').pop().toLowerCase()

function LaneRail({ lane }) {
  return <span aria-hidden="true" style={{ flex: '0 0 4px', alignSelf: 'stretch', borderRadius: 4, background: lane.color }} />
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

function QueueRow({ f, decisions, selected, onSelect }) {
  const r = rowModel(f, decisions)
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
        borderLeft: selected ? `3px solid ${r.lane.color}` : '3px solid transparent',
      }}
    >
      <LaneRail lane={r.lane} />
      <span style={{ minWidth: 0, flex: '1 1 auto' }}>
        {/* Dominant text is the ISSUE, not the filename — the issue determines what to do next. */}
        <span style={{ display: 'block', fontWeight: r.unread ? 700 : 500, fontSize: 13.5,
                       whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {r.issue}
        </span>
        <span className="muted" style={{ display: 'block', fontSize: 12, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {r.file}{r.location ? ` · ${r.location}` : ''}
        </span>
        <span style={{ display: 'block', fontSize: 12, color: r.lane.color, marginTop: 2 }}>{r.did}</span>
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

function DetailPane({ f, decisions, onDecide, onOpenWord, onRecheck }) {
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
  const isManual = lane.key === 'manual'
  const resolved = isResolved(f, decisions)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ flex: '1 1 auto', overflowY: 'auto', padding: '18px 22px' }}>
        {/* 1 · What do I need to do? */}
        <p className="muted" style={{ fontSize: 11.5, letterSpacing: '.08em', textTransform: 'uppercase', margin: 0 }}>
          {isManual ? 'Manual remediation' : 'Review'}
        </p>
        <h3 style={{ margin: '4px 0 6px', fontSize: 19 }}>{r.issue}</h3>
        <p style={{ fontSize: 14, color: 'var(--ink)', margin: '0 0 4px' }}>{lane.didLine}.</p>
        <Meta row={{ ...r, wcag: (f.rule_id || f.ruleId || '') }} />

        {/* 2 · What changed? (or, for manual, how to change it) */}
        <div style={{ marginTop: 18 }}>
          <p className="muted" style={{ fontSize: 11.5, letterSpacing: '.08em', textTransform: 'uppercase', margin: '0 0 8px' }}>
            {isManual ? 'How to fix it' : 'What changed'}
          </p>
          {isManual ? <ManualSteps f={f} /> : <BeforeAfter f={f} />}
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
      <div style={{ flex: '0 0 auto', borderTop: '1px solid var(--line,#e2dce4)', padding: '12px 22px',
                    display: 'flex', gap: 10, alignItems: 'center', background: 'var(--bg, #fff)' }}>
        {resolved ? (
          <span className="muted" style={{ fontSize: 13 }}>✓ Resolved — nothing left to do on this finding.</span>
        ) : isManual ? (
          <>
            <button className="primary" onClick={() => onOpenWord?.(f)}>Open in Word</button>
            <button className="ghost" onClick={() => onRecheck?.(f)}>Upload &amp; recheck</button>
            <button className="ghost" onClick={() => onDecide?.(f, { state: 'assigned' })}>Assign</button>
          </>
        ) : (
          <>
            <button className="primary" onClick={() => onDecide?.(f, { state: 'accepted' })}>{lane.action}</button>
            <button className="ghost" onClick={() => onDecide?.(f, { state: 'rejected' })}>Reject</button>
            <button className="ghost" onClick={() => onOpenWord?.(f)}>Open in Word</button>
          </>
        )}
      </div>
    </div>
  )
}

export default function RemediationInbox({
  queue = [], decisions = {}, onDecide, onOpenWord, onRecheck,
  initialSort = 'priority', initialTab = 'all',
}) {
  const [selectedId, setSelectedId] = useState(null)
  const [tab, setTab] = useState(initialTab)
  const [sort, setSort] = useState(initialSort)
  const [search, setSearch] = useState('')
  const [collapsed, setCollapsed] = useState({}) // file -> true when a document group is collapsed

  const counts = useMemo(() => tabCounts(queue, decisions), [queue, decisions])
  const prog = useMemo(() => progress(queue, decisions), [queue, decisions])

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    const filtered = queue.filter((f) => matchesTab(f, tab, decisions) &&
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

  // Act on a finding, then auto-advance to the next unresolved one — the behaviour that makes the
  // queue feel like a controlled worklist rather than a scroll through an audit report.
  function act(f, decision) {
    onDecide?.(f, decision)
    const nextDecisions = { ...decisions, [f.id]: decision }
    const nxt = nextUnresolvedId(visible, f.id, nextDecisions)
    setSelectedId(nxt)
  }

  return (
    <div className="rinbox" style={{ display: 'flex', gap: 0, border: '1px solid var(--line,#e2dce4)', borderRadius: 12, overflow: 'hidden', minHeight: 480 }}>
      {/* ── Left: the work queue (38%) ── */}
      <div style={{ flex: '0 0 38%', maxWidth: '38%', borderRight: '1px solid var(--line,#e2dce4)', display: 'flex', flexDirection: 'column', minHeight: 480 }}>
        <div style={{ flex: '0 0 auto', padding: '10px 12px', borderBottom: '1px solid var(--line,#e2dce4)' }}>
          <input type="search" value={search} onChange={(e) => setSearch(e.target.value)}
                 placeholder="Search findings…" aria-label="Search findings"
                 style={{ width: '100%', fontSize: 13, padding: '6px 10px', borderRadius: 8, border: '1px solid var(--line,#e2dce4)' }} />
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
            {TABS.map((t) => (
              <button key={t} type="button" aria-pressed={tab === t} onClick={() => setTab(t)}
                      style={{ fontSize: 11.5, padding: '2px 9px', borderRadius: 20, cursor: 'pointer',
                               border: `1px solid ${tab === t ? 'var(--ink)' : 'var(--line,#e2dce4)'}`,
                               background: tab === t ? 'var(--ink)' : 'transparent', color: tab === t ? '#fff' : 'var(--ink)',
                               fontWeight: tab === t ? 700 : 500 }}>
                {TAB_LABEL[t]} {counts[t] > 0 ? counts[t] : ''}
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
            <label className="muted" style={{ fontSize: 11.5, display: 'flex', gap: 5, alignItems: 'center' }}>
              Sort
              <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort findings"
                      style={{ fontSize: 11.5, padding: '2px 6px', borderRadius: 6, border: '1px solid var(--line,#e2dce4)' }}>
                {SORTS.map((s) => <option key={s} value={s}>{SORT_LABEL[s]}</option>)}
              </select>
            </label>
            <span className="muted" style={{ fontSize: 11.5, fontWeight: 600 }}>{prog.resolved} of {prog.total} resolved</span>
          </div>
        </div>
        <div style={{ flex: '1 1 auto', overflowY: 'auto' }}>
          {visible.length === 0 ? (
            <p className="muted" style={{ padding: 16, fontSize: 13 }}>Nothing here. {tab !== 'all' && <button className="linklike" onClick={() => setTab('all')}>Show all</button>}</p>
          ) : groups.map((g) => (
            <div key={g.file}>
              <button type="button" onClick={() => setCollapsed((c) => ({ ...c, [g.file]: !c[g.file] }))}
                      style={{ display: 'flex', width: '100%', alignItems: 'center', gap: 8, padding: '6px 12px', cursor: 'pointer',
                               border: 'none', borderBottom: '1px solid var(--line,#e2dce4)', background: 'var(--surface-2,#f6f5f8)', fontSize: 12, fontWeight: 700 }}>
                <span aria-hidden="true">{collapsed[g.file] ? '▸' : '▾'}</span>
                <span style={{ flex: '1 1 auto', minWidth: 0, textAlign: 'left', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>📄 {g.file}</span>
                <span className="muted" style={{ fontWeight: 400 }}>{g.items.length}</span>
              </button>
              {!collapsed[g.file] && g.items.map((f) => (
                <QueueRow key={f.id} f={f} decisions={decisions} selected={f.id === selectedId} onSelect={setSelectedId} />
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* ── Right: the remediation workspace (62%) ── */}
      <div style={{ flex: '1 1 62%', minWidth: 0 }}>
        <DetailPane f={selected} decisions={decisions} onDecide={act} onOpenWord={onOpenWord} onRecheck={onRecheck} />
      </div>
    </div>
  )
}

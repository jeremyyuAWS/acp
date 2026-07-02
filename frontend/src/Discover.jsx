import { useState } from 'react'
import ScanTheater from './ScanTheater.jsx'
import SearchFilterBar, { useSearchFilter, matchesFilters } from './SearchFilterBar.jsx'
import WindowedRows from './WindowedRows.jsx'
import FileDrawer, { retentionOf } from './FileDrawer.jsx'
import SegmentDrawer from './SegmentDrawer.jsx'
import { Bars } from './charts.jsx'
import { DEPARTMENTS } from './sim.js'
import { dupeCountOf, duplicateFiles } from './dedupe.js'

const STATUS_TAGS = new Set(['certified', 'needs-review', 'auto-fixable', 'remediation-queued'])
const classTags = (f) => (f.tags || []).filter((t) => !STATUS_TAGS.has(t))
const RET_BUCKET = (f) => { if (f.locked) return 'locked'; const l = retentionOf(f).label; return l.startsWith('Retain') ? 'retain' : l.startsWith('Archive') ? 'archive' : 'keep' }
const RET_COLOR = { keep: '#639922', archive: '#7a5c8e', retain: '#D85A30', locked: '#9a948f', delete: '#1F5FA8' }
const RET_ORDER = ['keep', 'archive', 'retain']
const RET_BADGE = { keep: ['Keep', '#E7F0DC', '#3B6D11'], archive: ['Archive', '#EEEDFE', '#3C3489'], retain: ['Retain · legal hold', '#FAEEDA', '#854F0B'], locked: ['🔒 Could not open', '#EEEDEA', '#5F5E5A'], delete: ['Delete', '#E2EDFB', '#1F5FA8'] }
const RISK_COLOR = { PII: '#1F5FA8', 'legal-hold': '#854F0B', 'high-traffic': '#A56814' }
const TYPE_COLOR = { PDF: '#C2410C', DOCX: '#2563EB', PPTX: '#D97706', XLSX: '#15803D', HTML: '#7A5C8E', VIDEO: '#9333EA', AUDIO: '#0891B2' }
const CLASS_TAGS = ['PII', 'legal-hold', 'public-facing', 'high-traffic']
const CLASS_COLOR = { PII: '#1F5FA8', 'legal-hold': '#854F0B', 'public-facing': '#D85A30', 'high-traffic': '#A56814' }
const OVERRIDE_ACTIONS = ['keep', 'archive', 'retain', 'delete']

const SH = ({ n, label, desc, id }) => (
  <div id={id} style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '28px 0 10px', paddingTop: 16, borderTop: '1px solid var(--line)' }}>
    <b style={{ fontSize: 13.5, color: 'var(--ink)', whiteSpace: 'nowrap' }}>{n ? `${n} · ` : ''}{label}</b>
    {desc && <span className="muted" style={{ fontSize: 12 }}>{desc}</span>}
  </div>
)

// Windowed row rendering (150-at-a-time scroll sentinel) — shared with SegmentDrawer.

// Combined exposure + risk chart: top-level exposure (public-facing vs internal),
// with "internal" expandable to reveal the sensitive-content flags it carries.
function ExposureRisk({ pub, internal, internalRisk, onPick }) {
  const [open, setOpen] = useState(false)
  const mx = Math.max(1, pub.value, internal.value)
  // A clickable row used to be div[role=button] wrapping the count <button> — nested
  // interactive controls (axe: nested-interactive, WCAG 4.1.2). Now the LABEL is the
  // real button (keyboard/AT entry point) and the row div keeps a plain onClick only
  // as a wider mouse target — no role, so it isn't a second interactive control.
  const row = (label, value, color, mxx, { indent = false, chev = null, onClick, onPickCount } = {}) => {
    const labelInner = <>{chev && <span className="expchev" aria-hidden="true">{chev}</span>}{label}</>
    const inner = (<>
      {onClick
        ? <button className="critlabel" style={{ fontSize: 13, textAlign: 'left', paddingLeft: indent ? 18 : 0,
                                                 background: 'none', border: 'none', font: 'inherit', color: 'inherit', cursor: 'pointer' }}
                  onClick={(e) => { e.stopPropagation(); onClick(e) }}
                  aria-expanded={chev ? open : undefined}>{labelInner}</button>
        : <span className="critlabel" style={{ fontSize: 13, textAlign: 'left', paddingLeft: indent ? 18 : 0 }}>{labelInner}</span>}
      <span className="track"><i style={{ width: `${(value / mxx) * 100}%`, background: color, transition: 'width .9s ease' }} /></span>
      {onPickCount
        ? <button className="critn" style={{ cursor: 'pointer', textDecoration: 'underline', textDecorationStyle: 'dotted', background: 'none', border: 'none', padding: 0, font: 'inherit', color: 'inherit' }} onClick={(e) => { e.stopPropagation(); onPickCount() }} title="View these files">{value}</button>
        : <span className="critn">{value}</span>}
    </>)
    return onClick
      ? <div className="critrow pickrow" style={{ gridTemplateColumns: '150px 1fr 34px', width: '100%' }} onClick={onClick}>{inner}</div>
      : <div className="critrow" style={{ gridTemplateColumns: '150px 1fr 34px' }}>{inner}</div>
  }
  return (
    <div>
      {row(pub.label, pub.value, pub.color, mx, { onClick: () => onPick?.('public-facing'), onPickCount: () => onPick?.('public-facing') })}
      {row(internal.label, internal.value, internal.color, mx, { chev: open ? '▾' : '▸', onClick: () => setOpen((o) => !o), onPickCount: () => onPick?.('internal') })}
      {open && internalRisk.map((r) => <div key={r.label}>{row(r.label, r.value, r.color, internal.value, { indent: true, onClick: () => onPick?.(r.label) })}</div>)}
    </div>
  )
}

// decisions/setDecisions default to a local, throwaway useState when the caller doesn't
// pass them (matches every other optional-prop default in this file) -- App.jsx DOES pass
// its own persisted decisions state (time-travel's save/hydrate effects), which is what
// makes decide()/undoDec() below actually survive a reload instead of resetting on every
// visit to this tab, and is also what feeds the campaign "resolved" counts (ADR 0003
// Phase 4) real data instead of always reading 0.
export default function Discover({ sources, files, busy, onScan, delegations = {}, fileTypeConfig = {}, onAdvance, progress = null, scanPct = 0, scanStatus = '', scanId = null, decisions: decisionsProp, setDecisions: setDecisionsProp }) {
  const [sel, setSel] = useState(null)
  const [open, setOpen] = useState(() => new Set())
  const toggle = (d) => setOpen((s) => { const n = new Set(s); n.has(d) ? n.delete(d) : n.add(d); return n })
  // Cross-department search + facet filters — a match auto-expands ITS department
  // (search intent implies "show me", not "let me click to reveal") without disturbing
  // which departments the user had manually opened/closed before typing.
  const sf = useSearchFilter('discover')
  const [localDecisions, setLocalDecisions] = useState({})
  const decisions = decisionsProp ?? localDecisions
  const setDecisions = setDecisionsProp ?? setLocalDecisions
  const [classState, setClassState] = useState({})
  const [editAct, setEditAct] = useState(null)
  const [seg, setSeg] = useState(null)

  const visibleFiles = Object.keys(fileTypeConfig).length
    ? files.filter((f) => fileTypeConfig[f.type] !== false)
    : files
  const excludedCount = files.length - visibleFiles.length
  const ownerOf = (f) => delegations[f.owner] || f.owner
  const isDelegated = (f) => !!delegations[f.owner]

  const groups = {}
  visibleFiles.forEach((f) => { const d = f.department || 'Unassigned'; (groups[d] = groups[d] || []).push(f) })
  const deptOrder = [...DEPARTMENTS.filter((d) => groups[d]), ...Object.keys(groups).filter((d) => !DEPARTMENTS.includes(d))]
  const lockedCount = visibleFiles.filter((f) => f.locked).length

  const PLUM = '#7a5c8e'
  const tagsOf = (f) => classState[f.file]?.tags ?? classTags(f).filter((t) => CLASS_TAGS.includes(t))
  const byType = Object.entries(visibleFiles.reduce((m, f) => { const k = (f.type || '').toUpperCase(); m[k] = (m[k] || 0) + 1; return m }, {})).sort((a, b) => b[1] - a[1]).map(([label, value]) => ({ label, value, color: TYPE_COLOR[label] || PLUM }))
  const internalDocs = visibleFiles.filter((f) => !tagsOf(f).includes('public-facing'))
  const exposurePub = { label: 'public-facing · high-traffic', value: visibleFiles.length - internalDocs.length, color: '#D85A30' }
  const exposureInternal = { label: 'internal', value: internalDocs.length, color: '#9a948f' }
  const internalRisk = ['PII', 'legal-hold', 'high-traffic'].map((t) => ({ label: t, value: internalDocs.filter((f) => tagsOf(f).includes(t)).length, color: RISK_COLOR[t] })).filter((d) => d.value)

  const isConfirmed = (f) => !!classState[f.file]?.confirmed
  const toggleTag = (f, t) => setClassState((s) => { const cur = s[f.file]?.tags ?? tagsOf(f); const next = cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]; return { ...s, [f.file]: { tags: next, confirmed: false } } })
  const confirmClass = (f) => setClassState((s) => ({ ...s, [f.file]: { tags: tagsOf(f), confirmed: true } }))
  const classConfirmed = files.filter(isConfirmed).length

  const dupeCount = dupeCountOf(files)
  const alreadyScored = files.filter((f) => f.score != null).length
  const alreadyRemediated = files.filter((f) => f.remediated_at || f.drive_write_url || f.acp_stamped).length

  const actionable = files.filter((f) => !f.locked)
  const effAction = (f) => { const d = decisions[f.file]; return d?.state === 'override' ? d.action : RET_BUCKET(f) }
  const decide = (f, dec) => { setDecisions((s) => ({ ...s, [f.file]: dec })); setEditAct(null) }
  const undoDec = (f) => setDecisions((s) => { const n = { ...s }; delete n[f.file]; return n })
  const dcount = (st) => actionable.filter((f) => decisions[f.file]?.state === st).length

  // Facets for the shared bar. tag/status read live component state (classState,
  // decisions), so the chips track the user's classification work as it happens.
  const SF_FACETS = [
    { key: 'tag', label: 'Tag', get: (f) => tagsOf(f) },
    { key: 'type', label: 'Type', get: (f) => (f.type || '').toUpperCase() },
    { key: 'status', label: 'Status', get: (f) => (f.locked ? ['locked'] : [isConfirmed(f) ? 'classified' : 'unclassified', decisions[f.file] ? 'decided' : 'undecided']) },
    { key: 'source', label: 'Source', get: (f) => f.sourceName },
  ]
  const sfMatch = matchesFilters(sf, SF_FACETS, (f) => f.file)
  const pendingActions = actionable.length - dcount('accepted') - dcount('override')
  const acceptAll = () => setDecisions((s) => { const n = { ...s }; actionable.forEach((f) => { if (!n[f.file]) n[f.file] = { state: 'accepted' } }); return n })

  // Inventory/Classify/Action are no longer formally separated tabs — one dept-grouped
  // list shows the file, its classification tags (colorful pills), and its lifecycle
  // action together, so a reviewer tags AND decides in the same row instead of hopping
  // between sections.
  const compBar = (fs) => {
    const c = { keep: 0, archive: 0, retain: 0 }; fs.forEach((f) => { const a = effAction(f); if (c[a] != null) c[a] += 1 })
    return <span className="deptbar" aria-hidden="true">{RET_ORDER.map((k) => c[k] ? <i key={k} style={{ width: `${(c[k] / fs.length) * 100}%`, background: RET_COLOR[k] }} title={`${c[k]} ${k}`} /> : null)}</span>
  }
  const deptNote = (fs) => {
    const tot = fs.filter((f) => !f.locked).length
    const classified = fs.filter(isConfirmed).length
    const decided = fs.filter((f) => decisions[f.file] && !f.locked).length
    return `${classified}/${tot} classified · ${decided}/${tot} decided`
  }

  const deptList = () => deptOrder.map((d) => {
    const deptFiles = groups[d]
    const fs = sf.active ? deptFiles.filter(sfMatch) : deptFiles
    if (sf.active && !fs.length) return null   // hide departments with no match while filtering
    const isOpen = sf.active ? true : open.has(d)
    return (
      <div className="deptcard" key={d}>
        <button className="deptheader" onClick={() => toggle(d)} aria-expanded={isOpen} disabled={sf.active}>
          <span className="deptchev" aria-hidden="true">{isOpen ? '▾' : '▸'}</span>
          <span className="deptname">{d}</span>
          <span className="muted deptcount">
            {sf.active ? `${fs.length} of ${deptFiles.length} match` : `${fs.length} docs · `}
            {!sf.active && <b style={{ color: 'var(--ink)', fontWeight: 500 }}>{deptNote(fs)}</b>}
          </span>
          {!sf.active && compBar(fs)}
        </button>
        {isOpen && (
          <div className="depttable">
            <WindowedRows items={fs} renderRow={(f) => {
              const meta = (
                <div className="filemeta">
                  <span className="srcpill">{f.sourceName}</span>
                  {f.locked
                    ? <span className="lockflag">🔒 {f.openIssue}</span>
                    : <span className="muted">{f.modifiedAge} · {f.views90d?.toLocaleString()} views/90d{f.superseded ? ' · superseded' : ''}
                        {isDelegated(f) && <span className="badge" style={{ marginLeft: 6, background: '#E7F0DC', color: '#3B6D11', fontSize: 10 }}>delegated → {ownerOf(f)}</span>}
                      </span>}
                </div>
              )
              return (
                <div className="drow" key={f.file}>
                  <div className="dmain">
                    <button className="remname" onClick={() => setSel(f)}>{f.file}</button>
                    {meta}
                  </div>
                  {f.locked && (() => {
                    const [l, bg, fg] = RET_BADGE.locked
                    return <span className="badge" style={{ background: bg, color: fg }}>{l}</span>
                  })()}
                  {!f.locked && (() => {
                    const a = effAction(f); const [l, bg, fg] = RET_BADGE[a]; const dec = decisions[f.file]
                    const bothPending = !isConfirmed(f) && !dec
                    return (
                      <div className="drowdecide">
                        <div className="classctl">
                          <span className="classchips">
                            {CLASS_TAGS.map((t) => { const on = tagsOf(f).includes(t); return (
                              <button key={t} className={on ? 'classchip on' : 'classchip'} style={on ? { background: CLASS_COLOR[t] + '22', color: CLASS_COLOR[t], borderColor: CLASS_COLOR[t] + '55' } : undefined} aria-pressed={on} onClick={() => toggleTag(f, t)} title={on ? `Remove ${t}` : `Add ${t}`}>{on ? '✓ ' : '+ '}{t}</button>
                            ) })}
                            {f.superseded && <span className="classchip on" style={{ background: '#EEEDFE', color: '#3C3489', borderColor: '#cdc9f0', cursor: 'default' }}>superseded</span>}
                          </span>
                          {isConfirmed(f) && <span className="dectag ok">✓ classified</span>}
                        </div>
                        <div className="actctl">
                          <span className="badge" style={{ background: bg, color: fg, borderLeft: `3px solid ${RET_COLOR[a]}` }} title={f.rec?.rationale || ''}>{l}</span>
                          {dec?.state === 'accepted' && <span className="dectag ok">✓ accepted</span>}
                          {dec?.state === 'override' && <span className="dectag ov">changed</span>}
                          {editAct === f.file ? (
                            <span className="modchips">
                              {OVERRIDE_ACTIONS.map((a2) => <button key={a2} className="modchip" style={{ color: RET_COLOR[a2] }} onClick={() => decide(f, a2 === RET_BUCKET(f) ? { state: 'accepted' } : { state: 'override', action: a2 })}>{RET_BADGE[a2][0]}</button>)}
                              <button className="modchip cancel" onClick={() => setEditAct(null)}>cancel</button>
                            </span>
                          ) : !dec ? (
                            <span className="decctl">
                              {bothPending
                                ? <button className="decbtn ok wide" title="Confirm classification & accept action" onClick={() => { confirmClass(f); decide(f, { state: 'accepted' }) }}>✓ accept both</button>
                                : <button className="decbtn ok" title="Accept recommendation" onClick={() => decide(f, { state: 'accepted' })}>✓</button>}
                              <button className="decbtn ed" title="Change action" onClick={() => setEditAct(f.file)}>✎</button>
                              {!isConfirmed(f) && !bothPending && <button className="decbtn ok wide" title="Confirm classification" onClick={() => confirmClass(f)}>tags ✓</button>}
                            </span>
                          ) : <button className="decbtn undo" title="Undo action" onClick={() => undoDec(f)}>↺</button>}
                        </div>
                      </div>
                    )
                  })()}
                </div>
              )
            }} />
          </div>
        )}
      </div>
    )
  })

  return (
    <>
      <div className="estatebar">
        <div>
          <b>{files.length} documents</b> discovered across {sources.length} sources · {Object.keys(groups).length} departments
          <div className="muted" style={{ marginTop: 2 }}>the agent crawls metadata, proposes a classification &amp; a lifecycle action — you confirm or override{lockedCount ? <> · <span className="lockwarn">🔒 {lockedCount} could not be opened (password-protected / unsupported)</span></> : null}{excludedCount > 0 ? <> · <span className="muted">{excludedCount} file{excludedCount !== 1 ? 's' : ''} excluded by file-type settings</span></> : null}</div>
        </div>
        <button disabled={busy} onClick={() => onScan('all')}>{busy ? 'scanning…' : 'Re-scan all sources'}</button>
      </div>

      <ScanTheater busy={busy} progress={progress} pct={scanPct} status={scanStatus} />

      {files.length === 0 ? (
        <p className="muted" style={{ marginTop: 20 }}>No documents yet — run a scan from Integrations.</p>
      ) : (() => {
        const needsAssessment = files.filter((f) => !f.locked && !f.remediated_at && !f.drive_write_url && !f.acp_stamped && f.score == null).length
        const totalWidth = files.length || 1
        return (
        <>
          <SH id="disc-documents" label="Documents" desc="grouped by department · click to expand · tag &amp; decide right in the row" />

          <SearchFilterBar ctl={sf} items={visibleFiles} facets={SF_FACETS}
                           placeholder="Search all departments by filename…" noun="documents" />

          <div className="typelegend">
            <span className="muted" style={{ fontSize: 12, marginRight: 2 }}>document types · click to view:</span>
            {byType.map((t) => (
              <button key={t.label} className="typekey" onClick={() => setSeg({ title: `${t.label} documents`, subtitle: `${t.value} of ${files.length} · across all departments`, files: files.filter((f) => (f.type || '').toUpperCase() === t.label) })}>
                <i style={{ background: t.color }} aria-hidden="true" />{t.label}<span className="muted"> · {t.value}</span>
              </button>
            ))}
          </div>

          {/* File breakdown — how total sums across categories */}
          <div className="filesplit" role="region" aria-label="File breakdown">
            <div className="filesplit-item">
              <span className="filesplit-n" style={{ color: 'var(--ink)' }}>{files.length}</span>
              <span className="filesplit-lbl">total scanned</span>
              <div className="filesplit-bar"><i style={{ width: '100%', background: '#7a5c8e' }} /></div>
            </div>
            <button className="filesplit-item" style={{ background: 'none', border: 'none', padding: 0, textAlign: 'left', cursor: alreadyRemediated ? 'pointer' : 'default' }}
                    disabled={!alreadyRemediated}
                    onClick={() => alreadyRemediated && setSeg({ title: 'Already remediated', subtitle: `${alreadyRemediated} files fixed in a prior or current pass`, files: files.filter((f) => f.remediated_at || f.drive_write_url || f.acp_stamped) })}>
              <span className="filesplit-n" style={{ color: '#3B6D11' }}>{alreadyRemediated}</span>
              <span className="filesplit-lbl">remediated ✓</span>
              <div className="filesplit-bar"><i style={{ width: `${(alreadyRemediated / totalWidth) * 100}%`, background: '#3B6D11' }} /></div>
            </button>
            <button className="filesplit-item" style={{ background: 'none', border: 'none', padding: 0, textAlign: 'left', cursor: alreadyScored && !alreadyRemediated ? 'pointer' : 'default' }}
                    disabled={!alreadyScored}
                    onClick={() => alreadyScored && setSeg({ title: 'Already assessed', subtitle: `${alreadyScored} files have a WCAG score from the scan`, files: files.filter((f) => f.score != null) })}>
              <span className="filesplit-n" style={{ color: '#2A5E9E' }}>{alreadyScored}</span>
              <span className="filesplit-lbl">assessed</span>
              <div className="filesplit-bar"><i style={{ width: `${(alreadyScored / totalWidth) * 100}%`, background: '#2A5E9E' }} /></div>
            </button>
            <button className="filesplit-item" style={{ background: 'none', border: 'none', padding: 0, textAlign: 'left', cursor: dupeCount ? 'pointer' : 'default' }}
                    disabled={!dupeCount}
                    onClick={() => dupeCount && setSeg({ title: 'Duplicate uploads', subtitle: `${dupeCount} extra copies of another document`, files: duplicateFiles(files) })}>
              <span className="filesplit-n" style={{ color: '#854F0B' }}>{dupeCount}</span>
              <span className="filesplit-lbl">duplicates</span>
              <div className="filesplit-bar"><i style={{ width: `${(dupeCount / totalWidth) * 100}%`, background: '#854F0B' }} /></div>
            </button>
            <button className="filesplit-item" style={{ background: 'none', border: 'none', padding: 0, textAlign: 'left', cursor: lockedCount ? 'pointer' : 'default' }}
                    disabled={!lockedCount}
                    onClick={() => lockedCount && setSeg({ title: 'Password-protected / unreadable', subtitle: `${lockedCount} files the engine could not open`, files: files.filter((f) => f.locked) })}>
              <span className="filesplit-n" style={{ color: '#75706A' }}>{lockedCount}</span>{/* ≥4.5:1 on white (was #9a948f · 3.0) */}
              <span className="filesplit-lbl">🔒 locked</span>
              <div className="filesplit-bar"><i style={{ width: `${(lockedCount / totalWidth) * 100}%`, background: '#9a948f' }} /></div>
            </button>
            <button className="filesplit-item" style={{ background: 'none', border: 'none', padding: 0, textAlign: 'left', cursor: needsAssessment ? 'pointer' : 'default' }}
                    disabled={!needsAssessment}
                    onClick={() => needsAssessment && setSeg({ title: 'Needs assessment', subtitle: `${needsAssessment} files not yet scored`, files: files.filter((f) => !f.locked && !f.remediated_at && !f.drive_write_url && !f.acp_stamped && f.score == null) })}>
              <span className="filesplit-n" style={{ color: '#1F5FA8' }}>{needsAssessment}</span>
              <span className="filesplit-lbl">need assessment</span>
              <div className="filesplit-bar"><i style={{ width: `${(needsAssessment / totalWidth) * 100}%`, background: '#1F5FA8' }} /></div>
            </button>
          </div>

          <div style={{ fontSize: 12.5, color: 'var(--ink)', background: '#F1EFF3', border: '1px solid var(--line)',
                        borderRadius: 8, padding: '9px 12px', margin: '0 0 12px', lineHeight: 1.5 }}>
            <b>How this works:</b> <strong>document type</strong> comes from the file format ·
            <strong> department</strong> &amp; <strong>exposure</strong> are inferred from the file name
            (e.g. <code>HR-</code>, <code>Legal-</code>, <code>Finance-</code>, <code>public-</code>, <code>-hold</code>) ·
            <strong> sensitive-data</strong> flags come from the scan (Deep scan) — confirm or correct any tag below,
            your edits win over the agent's guess. Each row also carries the agent's recommended{' '}
            <strong>lifecycle action</strong> (keep / archive / retain / delete) — accept it, override it, or use
            <strong> ✓ accept both</strong> to sign off on the tags &amp; the action in one click.
          </div>
          <div className="chartrow">
            <section className="panel"><h2>By exposure &amp; risk <span className="muted" style={{ fontWeight: 400 }}>· expand internal to see its risk flags</span></h2>
              <ExposureRisk pub={exposurePub} internal={exposureInternal} internalRisk={internalRisk} onPick={(tag) => {
                const filtered = tag === 'public-facing'
                  ? visibleFiles.filter((f) => tagsOf(f).includes('public-facing'))
                  : tag === 'internal'
                    ? visibleFiles.filter((f) => !tagsOf(f).includes('public-facing'))
                    : visibleFiles.filter((f) => !tagsOf(f).includes('public-facing') && tagsOf(f).includes(tag))
                setSeg({ title: `${tag} documents`, subtitle: `${filtered.length} file${filtered.length !== 1 ? 's' : ''}`, files: filtered })
              }} />
              <p className="muted ppfoot">Public-facing pages (also your high-traffic content) are the top legal-exposure surface under ADA / EAA. The {exposureInternal.value} internal documents carry the PII &amp; legal-hold content that matters most if mishandled.</p>
            </section>
            <section className="panel"><h2>By document type</h2><Bars items={byType} cols="70px 1fr 30px" /></section>
          </div>
          <div className="hitlbar">
            <span className="muted">Human-in-the-loop ·{' '}
              <b style={{ color: 'var(--ink)' }}>{classConfirmed}</b> of {files.length} classified ·{' '}
              <b style={{ color: 'var(--ink)' }}>{dcount('accepted')}</b> accepted · <b style={{ color: 'var(--ink)' }}>{dcount('override')}</b> changed
            </span>
          </div>
          {deptList()}
        </>
        )
      })()}

      {files.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 12,
                      margin: '20px 0 4px', paddingTop: 14, borderTop: '1px solid var(--line)' }}>
          {pendingActions > 0 ? (
            <>
              <span className="muted" style={{ fontSize: 13 }}>{pendingActions} action{pendingActions === 1 ? '' : 's'} pending</span>
              <button className="ghost" onClick={acceptAll}>✓ Accept all recommendations</button>
            </>
          ) : (
            <span className="muted" style={{ fontSize: 13, color: '#3B6D11' }}>✓ All recommendations decided — done here? Continue →</span>
          )}
          <button onClick={() => onAdvance?.()} disabled={pendingActions > 0}
                  title={pendingActions > 0 ? `${pendingActions} action${pendingActions === 1 ? '' : 's'} still pending — accept or override each row, or use "Accept all recommendations"` : undefined}>
            Assess — score vs WCAG →
          </button>
        </div>
      )}

      {seg && <SegmentDrawer title={seg.title} subtitle={seg.subtitle} files={seg.files} onClose={() => setSeg(null)} onPickFile={(f) => { setSeg(null); setSel(f) }} />}
      {sel && <FileDrawer file={sel} context="discover" onClose={() => setSel(null)} overrideOwner={ownerOf(sel)} delegatedFrom={isDelegated(sel) ? sel.owner : null} scanId={scanId} />}
    </>
  )
}

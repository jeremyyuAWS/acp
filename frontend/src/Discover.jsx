import { useState } from 'react'
import FileDrawer, { retentionOf } from './FileDrawer.jsx'
import { Bars } from './charts.jsx'
import { DEPARTMENTS } from './sim.js'

// Steps 1–3 isolated as sub-steps: 1 Inventory · 2 Classify (HITL: confirm/correct the
// agent's classification) · 3 Actions (HITL: accept/override the lifecycle action).
const STATUS_TAGS = new Set(['certified', 'needs-review', 'auto-fixable', 'remediation-queued'])
const classTags = (f) => (f.tags || []).filter((t) => !STATUS_TAGS.has(t))
const RET_BUCKET = (f) => { if (f.locked) return 'locked'; const l = retentionOf(f).label; return l.startsWith('Retain') ? 'retain' : l.startsWith('Archive') ? 'archive' : 'keep' }
const RET_COLOR = { keep: '#639922', archive: '#7a5c8e', retain: '#D85A30', locked: '#9a948f', delete: '#A32D2D' }
const RET_ORDER = ['keep', 'archive', 'retain']
const RET_BADGE = { keep: ['Keep', '#E7F0DC', '#3B6D11'], archive: ['Archive', '#EEEDFE', '#3C3489'], retain: ['Retain · legal hold', '#FAEEDA', '#854F0B'], locked: ['🔒 Could not open', '#EEEDEA', '#5F5E5A'], delete: ['Delete', '#FCEBEB', '#A32D2D'] }
const SUBS = [['inventory', '1 · Inventory'], ['classify', '2 · Classify'], ['retain', '3 · Actions']]
const RISK_COLOR = { PII: '#A32D2D', 'legal-hold': '#854F0B', 'high-traffic': '#BA7517' }
const TYPE_COLOR = { PDF: '#C0453B', DOCX: '#2563EB', PPTX: '#D97706', XLSX: '#15803D', HTML: '#7A5C8E', VIDEO: '#9333EA', AUDIO: '#0891B2' }
const CLASS_TAGS = ['PII', 'legal-hold', 'public-facing', 'high-traffic']
const CLASS_COLOR = { PII: '#A32D2D', 'legal-hold': '#854F0B', 'public-facing': '#D85A30', 'high-traffic': '#BA7517' }
const OVERRIDE_ACTIONS = ['keep', 'archive', 'retain', 'delete']

// Combined exposure + risk chart: top-level exposure (public-facing vs internal),
// with "internal" expandable to reveal the sensitive-content flags it carries.
function ExposureRisk({ pub, internal, internalRisk, onPick }) {
  const [open, setOpen] = useState(false)
  const mx = Math.max(1, pub.value, internal.value)
  const row = (label, value, color, mxx, { indent = false, chev = null, onClick } = {}) => {
    const inner = (<>
      <span className="critlabel" style={{ fontSize: 13, textAlign: 'left', paddingLeft: indent ? 18 : 0 }}>{chev && <span className="expchev" aria-hidden="true">{chev}</span>}{label}</span>
      <span className="track"><i style={{ width: `${(value / mxx) * 100}%`, background: color, transition: 'width .9s ease' }} /></span>
      <span className="critn">{value}</span>
    </>)
    return onClick
      ? <button className="critrow pickrow" style={{ gridTemplateColumns: '150px 1fr 34px', width: '100%' }} onClick={onClick} aria-expanded={chev ? open : undefined}>{inner}</button>
      : <div className="critrow" style={{ gridTemplateColumns: '150px 1fr 34px' }}>{inner}</div>
  }
  return (
    <div>
      {row(pub.label, pub.value, pub.color, mx, { onClick: () => onPick?.('public-facing') })}
      {row(internal.label, internal.value, internal.color, mx, { chev: open ? '▾' : '▸', onClick: () => setOpen((o) => !o) })}
      {open && internalRisk.map((r) => <div key={r.label}>{row(r.label, r.value, r.color, internal.value, { indent: true, onClick: () => onPick?.(r.label) })}</div>)}
    </div>
  )
}

export default function Discover({ sources, files, busy, onScan }) {
  const [sub, setSub] = useState('inventory')
  const [sel, setSel] = useState(null)
  const [open, setOpen] = useState(() => new Set())
  const toggle = (d) => setOpen((s) => { const n = new Set(s); n.has(d) ? n.delete(d) : n.add(d); return n })
  const [decisions, setDecisions] = useState({}) // Actions HITL: file -> { state:'accepted'|'override', action? }
  const [classState, setClassState] = useState({}) // Classify HITL: file -> { tags:[...], confirmed:bool }
  const [editAct, setEditAct] = useState(null) // file currently choosing an override action

  const groups = {}
  files.forEach((f) => { const d = f.department || 'Unassigned'; (groups[d] = groups[d] || []).push(f) })
  const deptOrder = [...DEPARTMENTS.filter((d) => groups[d]), ...Object.keys(groups).filter((d) => !DEPARTMENTS.includes(d))]
  const lockedCount = files.filter((f) => f.locked).length

  const PLUM = '#7a5c8e'
  const byType = Object.entries(files.reduce((m, f) => { const k = (f.type || '').toUpperCase(); m[k] = (m[k] || 0) + 1; return m }, {})).sort((a, b) => b[1] - a[1]).map(([label, value]) => ({ label, value, color: TYPE_COLOR[label] || PLUM }))
  const internalDocs = files.filter((f) => !(f.tags || []).includes('public-facing'))
  const exposurePub = { label: 'public-facing · high-traffic', value: files.length - internalDocs.length, color: '#D85A30' }
  const exposureInternal = { label: 'internal', value: internalDocs.length, color: '#9a948f' }
  const internalRisk = ['PII', 'legal-hold', 'high-traffic'].map((t) => ({ label: t, value: internalDocs.filter((f) => (f.tags || []).includes(t)).length, color: RISK_COLOR[t] })).filter((d) => d.value)

  // ---- Classify HITL ----
  const tagsOf = (f) => classState[f.file]?.tags ?? classTags(f).filter((t) => CLASS_TAGS.includes(t))
  const isConfirmed = (f) => !!classState[f.file]?.confirmed
  const toggleTag = (f, t) => setClassState((s) => { const cur = s[f.file]?.tags ?? tagsOf(f); const next = cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]; return { ...s, [f.file]: { tags: next, confirmed: false } } })
  const confirmClass = (f) => setClassState((s) => ({ ...s, [f.file]: { tags: tagsOf(f), confirmed: true } }))
  const classConfirmed = files.filter(isConfirmed).length

  // ---- Actions HITL ----
  const actionable = files.filter((f) => !f.locked)
  const effAction = (f) => { const d = decisions[f.file]; return d?.state === 'override' ? d.action : RET_BUCKET(f) }
  const decide = (f, dec) => { setDecisions((s) => ({ ...s, [f.file]: dec })); setEditAct(null) }
  const undoDec = (f) => setDecisions((s) => { const n = { ...s }; delete n[f.file]; return n })
  const dcount = (st) => actionable.filter((f) => decisions[f.file]?.state === st).length
  const pendingActions = actionable.length - dcount('accepted') - dcount('override')
  const acceptAll = () => setDecisions((s) => { const n = { ...s }; actionable.forEach((f) => { if (!n[f.file]) n[f.file] = { state: 'accepted' } }); return n })

  // Per-department mini composition bar for the collapsed header.
  const compBar = (fs, mode) => {
    if (mode === 'inventory') {
      const m = {}; fs.forEach((f) => { const k = (f.type || '').toUpperCase(); m[k] = (m[k] || 0) + 1 })
      const segs = Object.entries(m).sort((a, b) => b[1] - a[1])
      return <span className="deptbar" aria-hidden="true">{segs.map(([k, n]) => <i key={k} style={{ width: `${(n / fs.length) * 100}%`, background: TYPE_COLOR[k] || PLUM }} title={`${n} ${k}`} />)}</span>
    }
    if (mode === 'retain') {
      const c = { keep: 0, archive: 0, retain: 0 }; fs.forEach((f) => { const a = effAction(f); if (c[a] != null) c[a] += 1 })
      return <span className="deptbar" aria-hidden="true">{RET_ORDER.map((k) => c[k] ? <i key={k} style={{ width: `${(c[k] / fs.length) * 100}%`, background: RET_COLOR[k] }} title={`${c[k]} ${k}`} /> : null)}</span>
    }
    return null
  }
  // Per-department secondary count for the header (HITL progress, no risk numbers).
  const deptNote = (fs, mode) => {
    if (mode === 'classify') { const done = fs.filter(isConfirmed).length; return `${done}/${fs.length} confirmed` }
    if (mode === 'retain') { const done = fs.filter((f) => decisions[f.file] && !f.locked).length; const tot = fs.filter((f) => !f.locked).length; return `${done}/${tot} decided` }
    return `${fs.length} document${fs.length === 1 ? '' : 's'}`
  }

  const deptList = (mode) => deptOrder.map((d) => {
    const fs = groups[d]
    const isOpen = open.has(d)
    return (
      <div className="deptcard" key={d}>
        <button className="deptheader" onClick={() => toggle(d)} aria-expanded={isOpen}>
          <span className="deptchev" aria-hidden="true">{isOpen ? '▾' : '▸'}</span>
          <span className="deptname">{d}</span>
          <span className="muted deptcount">{mode === 'inventory' ? `${fs.length} document${fs.length === 1 ? '' : 's'}` : <>{fs.length} docs · <b style={{ color: 'var(--ink)', fontWeight: 500 }}>{deptNote(fs, mode)}</b></>}</span>
          {compBar(fs, mode)}
        </button>
        {isOpen && (
          <div className="depttable">
            {fs.map((f) => {
              const meta = (
                <div className="filemeta">
                  <span className="srcpill">{f.sourceName}</span>
                  {f.locked
                    ? <span className="lockflag">🔒 {f.openIssue}</span>
                    : <span className="muted">{f.modifiedAge} · {f.views90d?.toLocaleString()} views/90d{f.superseded ? ' · superseded' : ''}</span>}
                </div>
              )
              return (
                <div className="drow" key={f.file}>
                  <div className="dmain">
                    <button className="remname" onClick={() => setSel(f)}>{f.file}</button>
                    {meta}
                  </div>
                  {mode === 'classify' && !f.locked && (
                    <div className="classctl">
                      <span className="classchips">
                        {CLASS_TAGS.map((t) => { const on = tagsOf(f).includes(t); return (
                          <button key={t} className={on ? 'classchip on' : 'classchip'} style={on ? { background: CLASS_COLOR[t] + '22', color: CLASS_COLOR[t], borderColor: CLASS_COLOR[t] + '55' } : undefined} aria-pressed={on} onClick={() => toggleTag(f, t)} title={on ? `Remove ${t}` : `Add ${t}`}>{on ? '✓ ' : '+ '}{t}</button>
                        ) })}
                      </span>
                      {isConfirmed(f)
                        ? <span className="dectag ok">✓ confirmed</span>
                        : <button className="decbtn ok" title="Confirm classification" onClick={() => confirmClass(f)}>✓</button>}
                    </div>
                  )}
                  {mode === 'retain' && (() => {
                    if (f.locked) { const [l, bg, fg] = RET_BADGE.locked; return <span className="badge" style={{ background: bg, color: fg }}>{l}</span> }
                    const a = effAction(f); const [l, bg, fg] = RET_BADGE[a]; const dec = decisions[f.file]
                    return (
                      <div className="actctl">
                        <span className="badge" style={{ background: bg, color: fg, borderLeft: `3px solid ${RET_COLOR[a]}` }}>{l}</span>
                        {dec?.state === 'accepted' && <span className="dectag ok">✓ accepted</span>}
                        {dec?.state === 'override' && <span className="dectag ov">changed</span>}
                        {editAct === f.file ? (
                          <span className="modchips">
                            {OVERRIDE_ACTIONS.map((a2) => <button key={a2} className="modchip" style={{ color: RET_COLOR[a2] }} onClick={() => decide(f, a2 === RET_BUCKET(f) ? { state: 'accepted' } : { state: 'override', action: a2 })}>{RET_BADGE[a2][0]}</button>)}
                            <button className="modchip cancel" onClick={() => setEditAct(null)}>cancel</button>
                          </span>
                        ) : !dec ? (
                          <span className="decctl">
                            <button className="decbtn ok" title="Accept recommendation" onClick={() => decide(f, { state: 'accepted' })}>✓</button>
                            <button className="decbtn ed" title="Change action" onClick={() => setEditAct(f.file)}>✎</button>
                          </span>
                        ) : <button className="decbtn undo" title="Undo" onClick={() => undoDec(f)}>↺</button>}
                      </div>
                    )
                  })()}
                </div>
              )
            })}
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
          <div className="muted" style={{ marginTop: 2 }}>the agent crawls metadata, proposes a classification &amp; a lifecycle action — you confirm or override{lockedCount ? <> · <span className="lockwarn">🔒 {lockedCount} could not be opened (password-protected / unsupported)</span></> : null}</div>
        </div>
        <button disabled={busy} onClick={() => onScan('all')}>{busy ? 'scanning…' : 'Re-scan all sources'}</button>
      </div>

      <div className="subtabs" role="tablist" aria-label="Discover steps">
        {SUBS.map(([k, label]) => <button key={k} role="tab" aria-selected={sub === k} className={sub === k ? 'fchip on' : 'fchip'} onClick={() => setSub(k)}>{label}</button>)}
      </div>

      {files.length === 0 ? <p className="muted">No documents yet — run a scan from Integrations.</p> : sub === 'classify' ? (
        <>
          <div className="muted" style={{ margin: '4px 0 10px' }}>Step 2 · how the agent classifies the estate by content &amp; risk — expand a department to <b>confirm or correct</b> each document’s tags</div>
          <div className="chartrow">
            <section className="panel"><h2>By exposure &amp; risk <span className="muted" style={{ fontWeight: 400 }}>· expand internal to see its risk flags</span></h2>
              <ExposureRisk pub={exposurePub} internal={exposureInternal} internalRisk={internalRisk} />
              <p className="muted ppfoot">Public-facing pages (also your high-traffic content) are the top legal-exposure surface under ADA / EAA. The {exposureInternal.value} internal documents carry the PII &amp; legal-hold content that matters most if mishandled.</p>
            </section>
            <section className="panel"><h2>By document type</h2><Bars items={byType} cols="70px 1fr 30px" /></section>
          </div>
          <div className="hitlbar">
            <span className="muted">Human-in-the-loop · <b style={{ color: 'var(--ink)' }}>{classConfirmed}</b> of {files.length} classifications confirmed</span>
            <span className="muted">expand a department below to review →</span>
          </div>
          {deptList('classify')}
        </>
      ) : (
        <>
          {sub === 'retain' && (
            <div className="hitlbar">
              <span className="muted"><b style={{ color: 'var(--ink)' }}>{dcount('accepted')}</b> accepted · <b style={{ color: 'var(--ink)' }}>{dcount('override')}</b> changed · {pendingActions} pending</span>
              <button disabled={!pendingActions} onClick={acceptAll}>✓ Accept all recommendations</button>
            </div>
          )}
          <div className="muted" style={{ margin: '4px 0 8px' }}>{sub === 'retain' ? 'Step 3 · Actions · the lifecycle action the agent recommends per document — accept it or change it to keep / archive / retain / delete' : 'Step 1 · inventory by department · click a department to expand · the bar shows its document-type mix'}</div>
          {deptList(sub === 'retain' ? 'retain' : 'inventory')}
        </>
      )}
      {sel && <FileDrawer file={sel} context="discover" onClose={() => setSel(null)} />}
    </>
  )
}

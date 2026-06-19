import { useState } from 'react'
import Tag from './Tag.jsx'
import FileDrawer, { retentionOf } from './FileDrawer.jsx'
import { Bars } from './charts.jsx'
import { DEPARTMENTS } from './sim.js'

// Steps 1–3 isolated as sub-steps: 1 Discover & Inventory · 2 Classify & Prioritize
// · 3 Retain / Archive / Delete. Pure lifecycle — no accessibility assessment.
const STATUS_TAGS = new Set(['certified', 'needs-review', 'auto-fixable', 'remediation-queued'])
const classTags = (f) => (f.tags || []).filter((t) => !STATUS_TAGS.has(t))
const RET_BUCKET = (f) => { if (f.locked) return 'locked'; const l = retentionOf(f).label; return l.startsWith('Retain') ? 'retain' : l.startsWith('Archive') ? 'archive' : 'keep' }
const RET_COLOR = { keep: '#639922', archive: '#7a5c8e', retain: '#D85A30', locked: '#9a948f' }
const RET_ORDER = ['keep', 'archive', 'retain', 'locked']
const RET_BADGE = { keep: ['Keep', '#E7F0DC', '#3B6D11'], archive: ['Archive', '#EEEDFE', '#3C3489'], retain: ['Retain · legal hold', '#FAEEDA', '#854F0B'], locked: ['🔒 Could not open', '#EEEDEA', '#5F5E5A'] }
const SUBS = [['inventory', '1 · Inventory'], ['classify', '2 · Classify'], ['retain', '3 · Actions']]
const RISK_COLOR = { PII: '#A32D2D', 'legal-hold': '#854F0B', 'high-traffic': '#BA7517' }

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

  const groups = {}
  files.forEach((f) => { const d = f.department || 'Unassigned'; (groups[d] = groups[d] || []).push(f) })
  const deptOrder = [...DEPARTMENTS.filter((d) => groups[d]), ...Object.keys(groups).filter((d) => !DEPARTMENTS.includes(d))]
  const lifecycleFlagged = files.filter((f) => RET_BUCKET(f) !== 'keep' && !f.locked).length
  const lockedCount = files.filter((f) => f.locked).length

  const PLUM = '#7a5c8e'
  const byType = Object.entries(files.reduce((m, f) => { const k = (f.type || '').toUpperCase(); m[k] = (m[k] || 0) + 1; return m }, {})).sort((a, b) => b[1] - a[1]).map(([label, value]) => ({ label, value, color: PLUM }))
  // Combined exposure + risk: public-facing (also the high-traffic set here) vs internal,
  // with internal expandable to the sensitive-content flags it actually carries.
  const internalDocs = files.filter((f) => !(f.tags || []).includes('public-facing'))
  const exposurePub = { label: 'public-facing · high-traffic', value: files.length - internalDocs.length, color: '#D85A30' }
  const exposureInternal = { label: 'internal', value: internalDocs.length, color: '#9a948f' }
  const internalRisk = ['PII', 'legal-hold', 'high-traffic'].map((t) => ({ label: t, value: internalDocs.filter((f) => (f.tags || []).includes(t)).length, color: RISK_COLOR[t] })).filter((d) => d.value)

  const deptList = (showRetain) => deptOrder.map((d) => {
    const fs = groups[d]
    const counts = { keep: 0, archive: 0, retain: 0 }
    fs.forEach((f) => { counts[RET_BUCKET(f)] += 1 })
    const pii = fs.filter((f) => (f.tags || []).includes('PII')).length
    const pub = fs.filter((f) => (f.tags || []).includes('public-facing')).length
    const isOpen = open.has(d)
    return (
      <div className="deptcard" key={d}>
        <button className="deptheader" onClick={() => toggle(d)} aria-expanded={isOpen}>
          <span className="deptchev" aria-hidden="true">{isOpen ? '▾' : '▸'}</span>
          <span className="deptname">{d}</span>
          <span className="muted deptcount">{fs.length} docs · {pii} PII · {pub} public-facing</span>
          {showRetain && <span className="deptbar" aria-hidden="true">{RET_ORDER.map((k) => counts[k] ? <i key={k} style={{ width: `${(counts[k] / fs.length) * 100}%`, background: RET_COLOR[k] }} title={`${counts[k]} ${k}`} /> : null)}</span>}
        </button>
        {isOpen && (
          <table className="depttable">
            <tbody>
              {fs.map((f) => {
                const rb = RET_BUCKET(f); const [rlabel, rbg, rfg] = RET_BADGE[rb]
                return (
                  <tr key={f.file} className="filerow" role="button" tabIndex={0}
                    onClick={() => setSel(f)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSel(f) } }}>
                    <td className="fname">{f.file}
                      <div className="filemeta">
                        <span className="srcpill">{f.sourceName}</span>
                        {f.locked
                          ? <span className="lockflag">🔒 {f.openIssue}</span>
                          : <span className="muted">{f.modifiedAge} · {f.views90d?.toLocaleString()} views/90d{f.superseded ? ' · superseded' : ''}</span>}
                        {classTags(f).slice(0, 3).map((t) => <Tag key={t} t={t} />)}
                      </div>
                    </td>
                    {showRetain && <td><span className="badge" style={{ background: rbg, color: rfg }}>{rlabel}</span></td>}
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    )
  })

  return (
    <>
      <div className="estatebar">
        <div>
          <b>{files.length} documents</b> discovered &amp; classified across {sources.length} sources · {Object.keys(groups).length} departments
          <div className="muted" style={{ marginTop: 2 }}>the agent crawls metadata, classifies by content &amp; risk, and flags lifecycle — {lifecycleFlagged} archive/legal-hold candidates{lockedCount ? <> · <span className="lockwarn">🔒 {lockedCount} could not be opened (password-protected / unsupported)</span></> : null}</div>
        </div>
        <button disabled={busy} onClick={() => onScan('all')}>{busy ? 'scanning…' : 'Re-scan all sources'}</button>
      </div>

      <div className="subtabs" role="tablist" aria-label="Discover steps">
        {SUBS.map(([k, label]) => <button key={k} role="tab" aria-selected={sub === k} className={sub === k ? 'fchip on' : 'fchip'} onClick={() => setSub(k)}>{label}</button>)}
      </div>

      {files.length === 0 ? <p className="muted">No documents yet — run a scan from Integrations.</p> : sub === 'classify' ? (
        <>
          <div className="muted" style={{ margin: '4px 0 10px' }}>Step 2 · how the agent classifies &amp; prioritizes the estate by content and risk</div>
          <div className="chartrow">
            <section className="panel"><h2>By exposure &amp; risk <span className="muted" style={{ fontWeight: 400 }}>· expand internal to see its risk flags</span></h2>
              <ExposureRisk pub={exposurePub} internal={exposureInternal} internalRisk={internalRisk} />
              <p className="muted ppfoot">Public-facing pages (also your high-traffic content) are the top legal-exposure surface under ADA / EAA. The {exposureInternal.value} internal documents carry the PII &amp; legal-hold content that matters most if mishandled.</p>
            </section>
            <section className="panel"><h2>By document type</h2><Bars items={byType} cols="70px 1fr 30px" /></section>
          </div>
        </>
      ) : (
        <>
          <div className="muted" style={{ margin: '4px 0 8px' }}>{sub === 'retain' ? 'Step 3 · Actions · the lifecycle action recommended per document — keep, archive, or retain (legal hold) — built from the inventory & classification above' : 'Step 1 · inventory by department · click a department to expand'}</div>
          {deptList(sub === 'retain')}
        </>
      )}
      {sel && <FileDrawer file={sel} context="discover" onClose={() => setSel(null)} />}
    </>
  )
}

import { useState } from 'react'
import Tag from './Tag.jsx'
import FileDrawer, { retentionOf } from './FileDrawer.jsx'
import { DEPARTMENTS } from './sim.js'

// Steps 1–3: Discover & Inventory · Classify & Prioritize · Retain / Archive / Delete.
// Pure lifecycle — classification (tags, risk) and retention. Accessibility findings
// and scoring live in the Assess step; nothing assessment-related is shown here.
// Assessment-status tags (set by scoring) — excluded so Discover stays classification-only.
const STATUS_TAGS = new Set(['certified', 'needs-review', 'auto-fixable', 'remediation-queued'])
const classTags = (f) => (f.tags || []).filter((t) => !STATUS_TAGS.has(t))
const RET_BUCKET = (f) => { const l = retentionOf(f).label; return l.startsWith('Retain') ? 'retain' : l.startsWith('Archive') ? 'archive' : 'keep' }
const RET_COLOR = { keep: '#639922', archive: '#7a5c8e', retain: '#D85A30' }
const RET_ORDER = ['keep', 'archive', 'retain']
const RET_BADGE = { keep: ['Keep', '#E7F0DC', '#3B6D11'], archive: ['Archive', '#EEEDFE', '#3C3489'], retain: ['Retain · legal hold', '#FAEEDA', '#854F0B'] }

export default function Discover({ sources, files, busy, onScan }) {
  const [sel, setSel] = useState(null)
  const [open, setOpen] = useState(() => new Set())
  const toggle = (d) => setOpen((s) => { const n = new Set(s); n.has(d) ? n.delete(d) : n.add(d); return n })

  const groups = {}
  files.forEach((f) => { const d = f.department || 'Unassigned'; (groups[d] = groups[d] || []).push(f) })
  const deptOrder = [...DEPARTMENTS.filter((d) => groups[d]), ...Object.keys(groups).filter((d) => !DEPARTMENTS.includes(d))]
  const lifecycleFlagged = files.filter((f) => RET_BUCKET(f) !== 'keep').length

  return (
    <>
      <div className="estatebar">
        <div>
          <b>{files.length} documents</b> discovered &amp; classified across {sources.length} sources · {Object.keys(groups).length} departments
          <div className="muted" style={{ marginTop: 2 }}>the agent crawls metadata, tags each by content &amp; risk, and flags lifecycle — {lifecycleFlagged} are archive or legal-hold candidates</div>
        </div>
        <button disabled={busy} onClick={() => onScan('all')}>{busy ? 'scanning…' : 'Re-scan all sources'}</button>
      </div>

      {files.length === 0 ? <p className="muted">No documents yet — run a scan from Integrations.</p> : (
        <>
          <div className="muted" style={{ margin: '6px 0 8px' }}>Inventory by department · click a department to expand</div>
          {deptOrder.map((d) => {
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
                  <span className="deptbar" aria-hidden="true">
                    {RET_ORDER.map((k) => counts[k] ? <i key={k} style={{ width: `${(counts[k] / fs.length) * 100}%`, background: RET_COLOR[k] }} title={`${counts[k]} ${k}`} /> : null)}
                  </span>
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
                                <span className="muted">{f.modifiedAge} · {f.views90d?.toLocaleString()} views/90d{f.superseded ? ' · superseded' : ''}</span>
                                {classTags(f).slice(0, 3).map((t) => <Tag key={t} t={t} />)}
                              </div>
                            </td>
                            <td><span className="badge" style={{ background: rbg, color: rfg }}>{rlabel}</span></td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            )
          })}
        </>
      )}
      {sel && <FileDrawer file={sel} context="discover" onClose={() => setSel(null)} />}
    </>
  )
}

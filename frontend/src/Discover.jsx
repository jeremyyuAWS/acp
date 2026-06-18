import { useState } from 'react'
import Tag from './Tag.jsx'
import FileDrawer, { statusOf } from './FileDrawer.jsx'
import { DEPARTMENTS } from './sim.js'

// Steps 1-3: Discover & Inventory + Classify & Prioritize + Retain/Archive/Delete.
// Inventory is segregated by department; each header doubles as a count + status visual.
const PRIORITY = { unanalysable: ['high', '#FCEBEB', '#A32D2D'], issues: ['high', '#FCEBEB', '#A32D2D'],
  uncertain: ['medium', '#FAEEDA', '#854F0B'], certifiable: ['low', '#F1EFE8', '#5F5E5A'] }
function classify(f) { return PRIORITY[statusOf(f)] }
function retention(name, tags) {
  if (/temp|draft|copy|old|backup|2019|2020/.test(name.toLowerCase())) return ['archive', '#FAEEDA', '#854F0B']
  if ((tags || []).includes('legal-hold')) return ['retain (legal hold)', '#EEEDFE', '#3C3489']
  return ['keep', '#E7F0DC', '#3B6D11']
}
const SEGCOLOR = { certifiable: '#639922', issues: '#F5B400', uncertain: '#D85A30', unanalysable: '#9a948f' }
const SEGORDER = ['certifiable', 'issues', 'uncertain', 'unanalysable']

export default function Discover({ sources, files, busy, onScan }) {
  const [sel, setSel] = useState(null)
  const [open, setOpen] = useState(() => new Set())
  const toggle = (d) => setOpen((s) => { const n = new Set(s); n.has(d) ? n.delete(d) : n.add(d); return n })

  const groups = {}
  files.forEach((f) => { const d = f.department || 'Unassigned'; (groups[d] = groups[d] || []).push(f) })
  const deptOrder = [...DEPARTMENTS.filter((d) => groups[d]), ...Object.keys(groups).filter((d) => !DEPARTMENTS.includes(d))]

  return (
    <>
      <div className="estatebar">
        <div>
          <b>{files.length} documents</b> discovered &amp; classified across {sources.length} sources · {Object.keys(groups).length} departments
          <div className="muted" style={{ marginTop: 2 }}>the agent auto-tags each by content, risk (PII, legal-hold), and public exposure</div>
        </div>
        <button disabled={busy} onClick={() => onScan('all')}>{busy ? 'scanning…' : 'Re-scan all sources'}</button>
      </div>

      {files.length === 0 ? <p className="muted">No documents yet — run a scan from Integrations.</p> : (
        <>
          <div className="muted" style={{ margin: '6px 0 8px' }}>Inventory by department · click a department to expand</div>
          {deptOrder.map((d) => {
            const fs = groups[d]
            const counts = { certifiable: 0, issues: 0, uncertain: 0, unanalysable: 0 }
            fs.forEach((f) => { counts[statusOf(f)] += 1 })
            const isOpen = open.has(d)
            return (
              <div className="deptcard" key={d}>
                <button className="deptheader" onClick={() => toggle(d)} aria-expanded={isOpen}>
                  <span className="deptchev" aria-hidden="true">{isOpen ? '▾' : '▸'}</span>
                  <span className="deptname">{d}</span>
                  <span className="muted deptcount">{fs.length} docs · {counts.certifiable} certifiable</span>
                  <span className="deptbar" aria-hidden="true">
                    {SEGORDER.map((k) => counts[k] ? <i key={k} style={{ width: `${(counts[k] / fs.length) * 100}%`, background: SEGCOLOR[k] }} title={`${counts[k]} ${k}`} /> : null)}
                  </span>
                </button>
                {isOpen && (
                  <table className="depttable">
                    <tbody>
                      {fs.map((f) => {
                        const [p, pbg, pfg] = classify(f); const [r, rbg, rfg] = retention(f.file, f.tags)
                        return (
                          <tr key={f.file} className="filerow" role="button" tabIndex={0}
                            onClick={() => setSel(f)}
                            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSel(f) } }}>
                            <td className="fname">{f.file}
                              <div className="filemeta">
                                <span className="srcpill">{f.sourceName}</span>
                                {(f.tags || []).slice(0, 4).map((t) => <Tag key={t} t={t} />)}
                              </div>
                            </td>
                            <td><span className="badge" style={{ background: pbg, color: pfg }}>{p}</span></td>
                            <td><span className="badge" style={{ background: rbg, color: rfg }}>{r}</span></td>
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
      {sel && <FileDrawer file={sel} onClose={() => setSel(null)} />}
    </>
  )
}

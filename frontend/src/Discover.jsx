import { useState } from 'react'
import Tag from './Tag.jsx'
import FileDrawer, { statusOf, REC_STYLE, fmtEffort } from './FileDrawer.jsx'
import { DEPARTMENTS, recommendationSummary } from './sim.js'

// Steps 1-3: Discover & Inventory + Classify & Prioritize + Retain/Archive/Delete.
// The agent's crawl metadata + findings resolve to a single prescriptive action
// per document (with an effort estimate); the estate band rolls them up.
const SEGCOLOR = { certifiable: '#639922', issues: '#F5B400', uncertain: '#D85A30', unanalysable: '#9a948f' }
const SEGORDER = ['certifiable', 'issues', 'uncertain', 'unanalysable']
const hrs = (m) => m >= 90 ? `${(m / 60).toFixed(1)} hrs` : `${Math.round(m)} min`

export default function Discover({ sources, files, busy, onScan }) {
  const [sel, setSel] = useState(null)
  const [open, setOpen] = useState(() => new Set())
  const toggle = (d) => setOpen((s) => { const n = new Set(s); n.has(d) ? n.delete(d) : n.add(d); return n })

  const groups = {}
  files.forEach((f) => { const d = f.department || 'Unassigned'; (groups[d] = groups[d] || []).push(f) })
  const deptOrder = [...DEPARTMENTS.filter((d) => groups[d]), ...Object.keys(groups).filter((d) => !DEPARTMENTS.includes(d))]
  const plan = files.length ? recommendationSummary(files) : null

  return (
    <>
      <div className="estatebar">
        <div>
          <b>{files.length} documents</b> discovered &amp; classified across {sources.length} sources · {Object.keys(groups).length} departments
          <div className="muted" style={{ marginTop: 2 }}>the agent crawls metadata (age, traffic, versions) and findings to recommend a next action for each</div>
        </div>
        <button disabled={busy} onClick={() => onScan('all')}>{busy ? 'scanning…' : 'Re-scan all sources'}</button>
      </div>

      {plan && (
        <div className="planband">
          <div className="planhead">
            <div>
              <b>Recommended action plan</b>
              <div className="muted" style={{ marginTop: 2 }}>
                ≈ <b style={{ color: 'var(--ink)' }}>{hrs(plan.remediateMin)}</b> of remediation across {plan.remediableDocs} documents · <b style={{ color: '#3B6D11' }}>{plan.autoPct}% fully automatic</b> · saves ≈ <b style={{ color: '#3B6D11' }}>{hrs(plan.savedMin)}</b> vs. manual
              </div>
            </div>
          </div>
          <div className="plancards">
            {plan.buckets.map((b) => {
              const [label, bg, fg, icon] = REC_STYLE[b.action] || REC_STYLE.review
              return (
                <div className="plancard" key={b.action} style={{ background: bg }}>
                  <div className="plancardtop" style={{ color: fg }}><span>{icon}</span><b>{b.n}</b></div>
                  <div className="plancardlbl" style={{ color: fg }}>{label}</div>
                  <div className="muted plancardeta">{b.action === 'keep' ? 'no work' : b.action === 'manual' ? `~${hrs(b.min)} manual` : `~${hrs(b.min)}`}</div>
                </div>
              )
            })}
          </div>
        </div>
      )}

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
                        const rec = f.rec || {}; const [label, rbg, rfg, icon] = REC_STYLE[rec.action] || REC_STYLE.review
                        return (
                          <tr key={f.file} className="filerow" role="button" tabIndex={0}
                            onClick={() => setSel(f)}
                            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSel(f) } }}>
                            <td className="fname">{f.file}
                              <div className="filemeta">
                                <span className="srcpill">{f.sourceName}</span>
                                <span className="muted">{f.modifiedAge} · {f.views90d?.toLocaleString()} views/90d{f.superseded ? ' · superseded' : ''}</span>
                                {(f.tags || []).slice(0, 2).map((t) => <Tag key={t} t={t} />)}
                              </div>
                            </td>
                            <td><span className="badge" style={{ background: rbg, color: rfg }}>{icon} {label}</span></td>
                            <td className="etacell">{fmtEffort(rec.etaMin)}{rec.confidence != null && <div className="muted" style={{ fontSize: 11 }}>{rec.confidence}% conf.</div>}</td>
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

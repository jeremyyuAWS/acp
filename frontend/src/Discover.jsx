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
const ACTIONS = ['auto', 'assisted', 'review', 'archive', 'keep', 'manual']
const ETA_OVERRIDE = { archive: 2, keep: 0, manual: 35, review: 10 }
const ACTION_DESC = {
  auto: 'The agent fixes these mechanically — alt text, headings, language, titles — then re-validates. No human needed.',
  assisted: 'AI proposes the fix; a human approves before publish. For critical, sensitive, contrast/link, or media (captions) findings.',
  review: 'A rule couldn’t be auto-evaluated. A reviewer confirms before the document can be certified.',
  archive: 'Compliant-but-stale, superseded, or low-traffic — archived to shrink the audited estate instead of spending effort.',
  keep: 'Already certifiable. Kept published and under continuous monitoring for drift.',
  manual: 'Unreadable source — a human must re-author or re-export the file before it can be assessed.',
}

export default function Discover({ sources, files, busy, onScan, decisions = {}, setDecisions }) {
  const [sel, setSel] = useState(null)
  const [open, setOpen] = useState(() => new Set())
  const [editing, setEditing] = useState(null)
  const toggle = (d) => setOpen((s) => { const n = new Set(s); n.has(d) ? n.delete(d) : n.add(d); return n })
  const decide = (file, d) => { setDecisions((s) => ({ ...s, [file]: d })); setEditing(null) }
  const undo = (file) => setDecisions((s) => { const n = { ...s }; delete n[file]; return n })
  const acceptAll = () => setDecisions((s) => { const n = { ...s }; files.forEach((f) => { if (!n[f.file]) n[f.file] = { state: 'accepted' } }); return n })
  const dvals = files.map((f) => decisions[f.file])
  const dcount = (st) => dvals.filter((d) => d?.state === st).length
  const pending = files.length - dcount('accepted') - dcount('override') - dcount('rejected')

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
            <div className="plandec">
              <span className="muted">{dcount('accepted')} accepted · {dcount('override')} modified · {dcount('rejected')} rejected · {pending} pending</span>
              <button disabled={!pending} onClick={acceptAll}>✓ Accept all</button>
            </div>
          </div>
          <div className="plancards">
            {plan.buckets.map((b) => {
              const [label, bg, fg, icon] = REC_STYLE[b.action] || REC_STYLE.review
              return (
                <div className="plancard" key={b.action} style={{ background: bg }} tabIndex={0} aria-label={`${label}: ${ACTION_DESC[b.action]}`}>
                  <div className="plancardtop" style={{ color: fg }}><span>{icon}</span><b>{b.n}</b></div>
                  <div className="plancardlbl" style={{ color: fg }}>{label}</div>
                  <div className="muted plancardeta">{b.action === 'keep' ? 'no work' : b.action === 'manual' ? `~${hrs(b.min)} manual` : `~${hrs(b.min)}`}</div>
                  <div className="plantip" role="tooltip"><b style={{ color: fg }}>{icon} {label}</b>{ACTION_DESC[b.action]}</div>
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
                        const rec = f.rec || {}; const dec = decisions[f.file]
                        const effAction = dec?.state === 'override' ? dec.action : rec.action
                        const [label, rbg, rfg, icon] = REC_STYLE[effAction] || REC_STYLE.review
                        const effEta = dec?.state === 'override' ? (ETA_OVERRIDE[dec.action] ?? rec.etaMin) : rec.etaMin
                        return (
                          <tr key={f.file} className={`filerow${dec?.state === 'rejected' ? ' rowrej' : ''}`} role="button" tabIndex={0}
                            onClick={() => setSel(f)}
                            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSel(f) } }}>
                            <td className="fname">{f.file}
                              <div className="filemeta">
                                <span className="srcpill">{f.sourceName}</span>
                                <span className="muted">{f.modifiedAge} · {f.views90d?.toLocaleString()} views/90d{f.superseded ? ' · superseded' : ''}</span>
                                {(f.tags || []).slice(0, 2).map((t) => <Tag key={t} t={t} />)}
                              </div>
                            </td>
                            <td className="reccell">
                              <span className="badge" style={{ background: rbg, color: rfg }}>{icon} {label}</span>
                              {dec?.state === 'accepted' && <span className="dectag ok">✓ accepted</span>}
                              {dec?.state === 'override' && <span className="dectag ov">modified</span>}
                              {dec?.state === 'rejected' && <span className="dectag rj">rejected</span>}
                              {editing === f.file ? (
                                <div className="modchips" onClick={(e) => e.stopPropagation()}>
                                  {ACTIONS.map((a) => { const [l, , fg, ic] = REC_STYLE[a]; return <button key={a} className="modchip" style={{ color: fg }} onClick={() => decide(f.file, a === rec.action ? { state: 'accepted' } : { state: 'override', action: a })}>{ic} {l}</button> })}
                                  <button className="modchip cancel" onClick={() => setEditing(null)}>cancel</button>
                                </div>
                              ) : (
                                <span className="decctl" onClick={(e) => e.stopPropagation()}>
                                  {!dec ? (<>
                                    <button className="decbtn ok" title="Accept recommendation" onClick={() => decide(f.file, { state: 'accepted' })}>✓</button>
                                    <button className="decbtn rj" title="Reject" onClick={() => decide(f.file, { state: 'rejected' })}>✕</button>
                                    <button className="decbtn ed" title="Modify action" onClick={() => setEditing(f.file)}>✎</button>
                                  </>) : <button className="decbtn undo" title="Undo" onClick={() => undo(f.file)}>↺</button>}
                                </span>
                              )}
                            </td>
                            <td className="etacell">{fmtEffort(effEta)}{rec.confidence != null && !dec && <div className="muted" style={{ fontSize: 11 }}>{rec.confidence}% conf.</div>}</td>
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

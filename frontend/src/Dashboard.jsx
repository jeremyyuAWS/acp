import { useState } from 'react'
import { reportUrl } from './api'
import { ScoreRing, Sparkline } from './ScoreRing.jsx'
import { Donut, Bars, statusSegments, severityItems } from './charts.jsx'
import FileDrawer from './FileDrawer.jsx'
import Tag from './Tag.jsx'
import Insight from './Insight.jsx'

const CRIT = {
  SC_1_1_1: '1.1.1 non-text', SC_1_3_1: '1.3.1 structure', SC_2_4_2: '2.4.2 page titled',
  SC_2_4_4: '2.4.4 link purpose', SC_3_1_1: '3.1.1 language',
}
const scoreColor = (s) => (s >= 90 ? '#639922' : s >= 50 ? '#F5B400' : '#F0524A')
const statusOf = (f) => (f.status === 'error' ? 'unanalysable' : f.status === 'uncertain' ? 'uncertain' : f.compliant ? 'certifiable' : 'issues')
const BADGE = {
  certifiable: ['#E7F0DC', '#3B6D11'], issues: ['#FAEEDA', '#854F0B'],
  uncertain: ['#FAECE7', '#993C1D'], unanalysable: ['#EEEDEA', '#5F5E5A'],
}

export default function Dashboard({ run, files, trend, delta, deltaKey }) {
  const [sel, setSel] = useState(null)
  const critFails = {}
  files.forEach((f) => new Set(f.issues.map((i) => i.wcag)).forEach((c) => { critFails[c] = (critFails[c] || 0) + 1 }))
  const maxFail = Math.max(1, ...Object.values(critFails))

  const pctOf = (a, b) => (b ? Math.round((a / b) * 100) : 0)
  const sevList = severityItems(files)
  const sevTotal = sevList.reduce((a, s) => a + s.value, 0)
  const sevHigh = sevList.filter((s) => s.label === 'critical' || s.label === 'serious').reduce((a, s) => a + s.value, 0)
  const topCrit = Object.entries(critFails).sort((a, b) => b[1] - a[1])[0]
  const INS = {
    status: `${pctOf(run.certifiable, run.files)}% of documents are certifiable. The ${run.uncertain} 'uncertain' docs had a rule that couldn't be evaluated — re-scanning with full access usually clears most; the rest are largely auto-fixable.`,
    severity: sevTotal ? `Critical & serious make up ${pctOf(sevHigh, sevTotal)}% of findings — ${pctOf(sevHigh, sevTotal) > 40 ? 'above' : 'near'} the ~40% norm. Front-load alt-text and tagging fixes for the biggest risk reduction.` : 'No open findings.',
    wcag: topCrit ? `${CRIT[topCrit[0]] ?? topCrit[0]} fails in the most files (${topCrit[1]}). It's a single, largely automatable fix class — a strong first remediation target.` : '',
  }

  return (
    <>
      <div className="dashtoolbar">
        <a className="exportbtn" href={reportUrl(run.id)} target="_blank" rel="noreferrer">⤓ Export PDF report</a>
      </div>
      <section className="hero">
        <ScoreRing score={run.avg_score} delta={delta} deltaKey={deltaKey} />
        <div className="heroright">
          <div className="herostats">
            <div className="herostat"><b style={{ color: '#3B6D11' }}>{run.certifiable}</b><span>certifiable</span></div>
            <div className="herostat"><b style={{ color: '#854F0B' }}>{run.uncertain}</b><span>uncertain</span></div>
            <div className="herostat"><b style={{ color: '#A32D2D' }}>{run.error}</b><span>unanalysable</span></div>
            <div className="herostat"><b>{run.files}</b><span>files</span></div>
          </div>
          {trend.length > 1 && new Set(trend).size > 1 && (
            <div className="herotrend">
              <span className="muted">compliance trend · {trend.length} scans</span>
              <Sparkline points={trend} />
            </div>
          )}
        </div>
      </section>
      <div className="chartrow">
        <section className="panel"><h2>Compliance status</h2><Donut segments={statusSegments(run)} caption="documents" /><Insight text={INS.status} /></section>
        <section className="panel"><h2>Findings by severity</h2>
          {severityItems(files).length ? <Bars items={severityItems(files)} /> : <p className="muted">No open findings.</p>}
          <Insight text={INS.severity} />
        </section>
      </div>
      {Object.keys(critFails).length > 0 && (
        <section className="panel">
          <h2>WCAG 2.1 criteria failing, by file count</h2>
          {Object.entries(critFails).sort((a, b) => b[1] - a[1]).map(([c, n]) => (
            <div className="critrow" key={c}>
              <span className="critlabel">{CRIT[c] ?? c}</span>
              <span className="track"><i style={{ width: `${(n / maxFail) * 100}%`, background: n >= maxFail ? '#F0524A' : '#F5B400' }} /></span>
              <span className="critn">{n}</span>
            </div>
          ))}
          <Insight text={INS.wcag} />
        </section>
      )}
      <section className="panel">
        <h2>File inventory · <span style={{ fontWeight: 400 }}>click a row for details</span></h2>
        <table>
          <thead><tr><th>file</th><th>status</th><th>score</th><th>findings</th></tr></thead>
          <tbody>
            {files.map((f) => {
              const st = statusOf(f); const [bg, fg] = BADGE[st]
              return (
                <tr key={f.file} className="filerow" role="button" tabIndex={0}
                  onClick={() => setSel(f)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSel(f) } }}>
                  <td className="fname">{f.file}
                    <div className="filemeta">
                      {f.sourceName && <span className="srcpill">{f.sourceName}</span>}
                      {(f.tags || []).slice(0, 4).map((t) => <Tag key={t} t={t} />)}
                    </div>
                  </td>
                  <td><span className="badge" style={{ background: bg, color: fg }}>{st}</span></td>
                  <td>{f.score === null ? <span className="muted">n/a</span> : (
                    <span className="scorecell"><span>{st === 'uncertain' ? '≤' : ''}{f.score}</span>
                      <span className="track sm"><i style={{ width: `${f.score}%`, background: scoreColor(f.score) }} /></span></span>)}</td>
                  <td className="muted">{st === 'uncertain' ? `${f.skipped_rules} rule(s) skipped`
                    : f.issues.length ? `${f.issues.length} issue(s)` : (f.status === 'error' ? 'could not analyse' : 'clean')}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>
      {sel && <FileDrawer file={sel} onClose={() => setSel(null)} />}
    </>
  )
}

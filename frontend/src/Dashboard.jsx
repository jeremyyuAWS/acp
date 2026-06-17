import { reportUrl } from './api'
import { ScoreRing, Sparkline } from './ScoreRing.jsx'
import { Donut, Bars, statusSegments, severityItems } from './charts.jsx'

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
  const critFails = {}
  files.forEach((f) => new Set(f.issues.map((i) => i.wcag)).forEach((c) => { critFails[c] = (critFails[c] || 0) + 1 }))
  const maxFail = Math.max(1, ...Object.values(critFails))

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
        <section className="panel"><h2>Compliance status</h2><Donut segments={statusSegments(run)} caption="documents" /></section>
        <section className="panel"><h2>Findings by severity</h2>
          {severityItems(files).length ? <Bars items={severityItems(files)} /> : <p className="muted">No open findings.</p>}
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
        </section>
      )}
      <section className="panel">
        <h2>File inventory</h2>
        <table>
          <thead><tr><th>file</th><th>status</th><th>score</th><th>findings</th></tr></thead>
          <tbody>
            {files.map((f) => {
              const st = statusOf(f); const [bg, fg] = BADGE[st]
              return (
                <tr key={f.file}>
                  <td className="fname">{f.file}</td>
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
    </>
  )
}

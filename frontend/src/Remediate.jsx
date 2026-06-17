// Steps 6-8: Automated Remediation + Human-in-the-Loop + Re-validate. Preview — the
// remediation engines aren't built yet; numbers are derived from the latest scan to feel real.
export default function Remediate({ run, files }) {
  const needFix = run ? Math.max(0, run.files - run.certifiable) : 0
  const totalIssues = files.reduce((a, f) => a + (f.issues?.length || 0), 0)
  const autoFixed = Math.round(totalIssues * 0.88)
  const routed = totalIssues - autoFixed

  const queue = [
    { icon: '▦', title: 'chart on slide 7 — alt-text', meta: 'confidence 61% · suggested: “Q3 revenue by region”' },
    { icon: '⊞', title: 'merged cells — table headers', meta: 'confidence 48% · needs a human structure call' },
    { icon: '¶', title: 'reading order — multi-column page', meta: 'confidence 55% · two plausible orders' },
  ]

  return (
    <>
      <div className="previewbar"><b>Preview</b> · remediation engines are on the roadmap — this shows the intended workflow on your live findings.</div>
      <div className="metrics">
        <div className="metric"><span>auto-fixed issues</span><b style={{ color: '#3B6D11' }}>{autoFixed}</b></div>
        <div className="metric"><span>routed to review</span><b style={{ color: '#854F0B' }}>{Math.max(routed, queue.length)}</b></div>
        <div className="metric"><span>files in remediation</span><b>{needFix}</b></div>
      </div>

      <section className="panel">
        <h2>Human-in-the-loop review queue</h2>
        <div className="queue">
          {queue.map((q) => (
            <div className="qrow" key={q.title}>
              <span className="qico" aria-hidden="true">{q.icon}</span>
              <div className="qmain">
                <div className="qtitle">{q.title}</div>
                <div className="qmeta">{q.meta}</div>
              </div>
              <button className="qbtn approve" disabled>✓ approve</button>
              <button className="qbtn reject" disabled>✕ reject</button>
            </div>
          ))}
        </div>
        <p className="muted" style={{ marginTop: 12 }}>↻ Re-validated against all engines after each fix — only re-passing files advance.</p>
      </section>
    </>
  )
}

// Steps 9-10: Publish/Replace/Archive + Monitor & Report. Preview — publish + continuous
// monitoring aren't wired yet; the document-journey trail is the audit-trail story made visible.
const JOURNEY = [
  { label: 'discovered', s: 'done' }, { label: 'classified', s: 'done' },
  { label: 'assessed 67', s: 'done' }, { label: 'auto-fixed', s: 'done' },
  { label: 'reviewed', s: 'done' }, { label: 'verified 100', s: 'done' },
  { label: 'published', s: 'now' }, { label: 'monitored', s: 'todo' },
]

export default function Report({ run }) {
  const certifiable = run ? run.certifiable : 0
  const published = certifiable
  const replaced = Math.round(certifiable * 0.75)
  const archived = certifiable - replaced

  return (
    <>
      <div className="previewbar"><b>Preview</b> · publish &amp; continuous monitoring are on the roadmap — assessment &amp; the audit trail are live.</div>
      <div className="metrics">
        <div className="metric"><span>published</span><b>{published}</b></div>
        <div className="metric"><span>replaced in place</span><b>{replaced}</b></div>
        <div className="metric"><span>archived</span><b>{archived}</b></div>
      </div>

      <section className="panel">
        <h2>Document journey · benefits-guide.pdf · full audit trail</h2>
        <div className="journey">
          {JOURNEY.map((j) => (
            <span className={`jstep ${j.s === 'now' ? 'now' : j.s === 'todo' ? 'todo' : ''}`} key={j.label}>
              {j.s === 'done' ? '✓' : j.s === 'now' ? '→' : '·'} {j.label}
            </span>
          ))}
        </div>
        <p className="muted" style={{ marginTop: 12 }}>Every action is logged immutably — who, when, which engine, what changed — for ADA / EAA evidence.</p>
      </section>

      <section className="panel">
        <div className="rubrichdr">
          <span className="muted">Continuous monitoring · weekly re-scan keeps the estate compliant as content changes</span>
          <button className="ghost" disabled>Executive summary</button>
        </div>
      </section>
    </>
  )
}

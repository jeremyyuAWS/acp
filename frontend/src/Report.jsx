import { useEffect, useRef, useState } from 'react'

// Steps 9-10: Publish/Archive + Monitor & Report. Preview — publish + monitoring aren't
// wired; this simulates the lifecycle, incl. a live audit-trail feed.
const JOURNEY = [
  { label: 'discovered', s: 'done' }, { label: 'classified', s: 'done' },
  { label: 'assessed 67', s: 'done' }, { label: 'auto-fixed', s: 'done' },
  { label: 'reviewed', s: 'done' }, { label: 'verified 100', s: 'done' },
  { label: 'published', s: 'now' }, { label: 'monitored', s: 'todo' },
]
const AUDIT = [
  ['auto-fix', 'alt-text added to figure 3', 'benefits-guide.pdf'],
  ['review', 'approved table-header fix', 'q3-board-deck.pptx'],
  ['publish', 'replaced in place', 'hr-policy-2026.docx'],
  ['re-scan', 'verified 100 / 100', 'onboarding.pdf'],
  ['archive', 'superseded version archived', '2019-policy-old.docx'],
  ['auto-fix', 'reading order corrected', 'annual-report.pdf'],
  ['review', 'rejected low-confidence alt-text', 'diagram.pptx'],
  ['publish', 'new compliant version published', 'benefits-guide.pdf'],
]
const ACTOR = { 'auto-fix': 'mova engine', review: 'A. Chen', publish: 'mova engine', 're-scan': 'mova engine', archive: 'mova engine' }
const ACOLOR = { 'auto-fix': '#1D9E75', review: '#854F0B', publish: '#185FA5', 're-scan': '#3B6D11', archive: '#5F5E5A' }

export default function Report({ run }) {
  const certifiable = run ? run.certifiable : 0
  const published = certifiable
  const replaced = Math.round(certifiable * 0.75)
  const archived = certifiable - replaced
  const before = run?.avg_score ?? 72
  const after = Math.min(100, before + 22)

  const [feed, setFeed] = useState(() => AUDIT.slice(0, 4).map((e, i) => ({ e, id: -i })))
  const next = useRef(1)
  useEffect(() => {
    const t = setInterval(() => {
      setFeed((f) => [{ e: AUDIT[next.current % AUDIT.length], id: next.current++ }, ...f].slice(0, 6))
    }, 2600)
    return () => clearInterval(t)
  }, [])

  return (
    <>
      <div className="previewbar"><b>Preview</b> · simulated publish, monitoring &amp; audit trail — assessment is live; this shows the full lifecycle.</div>
      <div className="metrics">
        <div className="metric"><span>published</span><b>{published}</b></div>
        <div className="metric"><span>replaced in place</span><b>{replaced}</b></div>
        <div className="metric"><span>archived</span><b>{archived}</b></div>
        <div className="metric"><span>next re-scan</span><b style={{ fontSize: 17 }}>in 6 days</b></div>
      </div>

      <div className="chartrow">
        <section className="panel">
          <h2>Compliance lift · after remediation</h2>
          <div className="lift">
            <div className="liftcol"><div className="liftnum" style={{ color: '#A32D2D' }}>{before}</div><div className="muted">before</div></div>
            <div className="liftarrow" aria-hidden="true">→</div>
            <div className="liftcol"><div className="liftnum" style={{ color: '#3B6D11' }}>{after}</div><div className="muted">after</div></div>
            <div className="liftgain">+{after - before} pts</div>
          </div>
          <p className="muted">Projected estate score once the queued fixes are approved and re-validated.</p>
        </section>
        <section className="panel">
          <h2>Document journey · benefits-guide.pdf</h2>
          <div className="journey">
            {JOURNEY.map((j) => (
              <span className={`jstep ${j.s === 'now' ? 'now' : j.s === 'todo' ? 'todo' : ''}`} key={j.label}>
                {j.s === 'done' ? '✓' : j.s === 'now' ? '→' : '·'} {j.label}
              </span>
            ))}
          </div>
        </section>
      </div>

      <section className="panel">
        <h2>Audit trail · live <span className="livedot" aria-hidden="true" /></h2>
        <div className="auditfeed">
          {feed.map((row) => {
            const [kind, what, file] = row.e
            return (
              <div className="auditrow" key={row.id}>
                <span className="auditkind" style={{ background: ACOLOR[kind] + '1f', color: ACOLOR[kind] }}>{kind}</span>
                <span className="auditwhat">{what} · <span className="fname" style={{ fontSize: 12 }}>{file}</span></span>
                <span className="muted auditactor">{ACTOR[kind]}</span>
              </div>
            )
          })}
        </div>
        <p className="muted" style={{ marginTop: 10 }}>Immutable who / when / what / which-engine log — your ADA &amp; EAA evidence trail.</p>
      </section>
    </>
  )
}

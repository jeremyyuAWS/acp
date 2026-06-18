import { useState } from 'react'
import { Bars } from './charts.jsx'
import ReviewDrawer from './ReviewDrawer.jsx'

// Steps 6-8: Automated Remediation + HITL + Re-validate. Preview — engines aren't built
// yet; this simulates the workflow (the review queue is interactive) on your live findings.
const FIX_TYPES = [
  { label: 'alt-text generated', value: 38, color: '#639922' },
  { label: 'reading order fixed', value: 21, color: '#1D9E75' },
  { label: 'headings tagged', value: 14, color: '#378ADD' },
  { label: 'language set', value: 9, color: '#7F77DD' },
  { label: 'table headers', value: 6, color: '#BA7517' },
]
const DIFF = {
  where: 'benefits-guide.pdf · figure 3', rule: 'WCAG 1.1.1 — non-text content',
  before: '<img src="chart.png">',
  after: '<img src="chart.png" alt="Q3 benefits enrollment by region — West 38%, Northeast 24%, South 22%, Midwest 16%">',
}
const QUEUE0 = [
  { id: 1, icon: '▦', title: 'chart on slide 7 — alt-text', meta: 'suggested alt-text', conf: 61, file: 'open-enrollment-deck.pptx', rule: 'WCAG 1.1.1 — non-text content',
    before: '<pic alt="">', after: '<pic alt="Q3 revenue by region — West 38%, NE 24%, South 22%, Midwest 16%">' },
  { id: 2, icon: '⊞', title: 'merged cells — table headers', meta: 'needs a human structure call', conf: 48, file: 'budget-model.xlsx', rule: 'WCAG 1.3.1 — info & relationships',
    before: '<table> — merged A1:C1, no header row', after: '<table> — unmerged, <th scope="col"> on row 1' },
  { id: 3, icon: '¶', title: 'reading order — multi-column page', meta: 'two plausible orders', conf: 55, file: 'annual-report-2025.pdf', rule: 'WCAG 1.3.2 — meaningful sequence',
    before: 'tab order: right column before left', after: 'tab order: left column → right (natural)' },
  { id: 4, icon: '◫', title: 'scanned page — needs OCR + tags', meta: 'low text confidence', conf: 42, file: 'vendor-contract-acme.pdf', rule: 'WCAG 1.3.1 — info & relationships',
    note: 'Image-only PDF — the agent recommends OCR + manual tagging before this can be certified; no auto-fix proposed.' },
]

export default function Remediate({ run, files }) {
  const needFix = run ? Math.max(0, run.files - run.certifiable) : 0
  const autoFixed = FIX_TYPES.reduce((a, f) => a + f.value, 0)
  const [queue, setQueue] = useState(QUEUE0)
  const [acted, setActed] = useState({ approved: 0, rejected: 0 })
  const [selItem, setSelItem] = useState(null)
  const act = (id, kind) => {
    setQueue((q) => q.filter((x) => x.id !== id))
    setActed((a) => ({ ...a, [kind]: a[kind] + 1 }))
    setSelItem(null)
  }

  return (
    <>
      <div className="previewbar"><b>Preview</b> · simulated remediation on your live findings — approve/reject items below to walk the loop.</div>
      <div className="metrics">
        <div className="metric"><span>auto-fixed issues</span><b style={{ color: '#3B6D11' }}>{autoFixed}</b></div>
        <div className="metric"><span>in review queue</span><b style={{ color: '#854F0B' }}>{queue.length}</b></div>
        <div className="metric"><span>approved</span><b>{acted.approved}</b></div>
        <div className="metric"><span>files in remediation</span><b>{needFix}</b></div>
      </div>

      <div className="chartrow">
        <section className="panel"><h2>Automated fixes applied · by type</h2><Bars items={FIX_TYPES} cols="140px 1fr 30px" /></section>
        <section className="panel">
          <h2>Before → after · AI alt-text</h2>
          <div className="muted" style={{ marginBottom: 8 }}>{DIFF.where} · {DIFF.rule}</div>
          <div className="diffbox before"><span className="difftag">before</span><code>{DIFF.before}</code></div>
          <div className="diffbox after"><span className="difftag">after</span><code>{DIFF.after}</code></div>
        </section>
      </div>

      <section className="panel">
        <h2>Human-in-the-loop review queue {queue.length === 0 && <span className="muted">· all clear</span>}</h2>
        {queue.length === 0 ? (
          <p className="muted">Queue cleared — {acted.approved} approved, {acted.rejected} rejected. Re-validation runs on the approved fixes.</p>
        ) : (
          <div className="queue">
            {queue.map((q) => (
              <div className="qrow clickable" key={q.id} role="button" tabIndex={0}
                onClick={() => setSelItem(q)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelItem(q) } }}>
                <span className="qico" aria-hidden="true">{q.icon}</span>
                <div className="qmain">
                  <div className="qtitle">{q.title} <span className="muted" style={{ fontSize: 12 }}>· {q.file}</span></div>
                  <div className="qmeta">{q.meta}</div>
                  <div className="conf">
                    <span className="conftrack"><i style={{ width: `${q.conf}%`, background: q.conf >= 55 ? '#F5B400' : '#F0524A' }} /></span>
                    <span className="muted">{q.conf}% confidence</span>
                  </div>
                </div>
                <button className="qbtn approve" onClick={(e) => { e.stopPropagation(); act(q.id, 'approved') }}>✓ approve</button>
                <button className="qbtn reject" onClick={(e) => { e.stopPropagation(); act(q.id, 'rejected') }}>✕ reject</button>
              </div>
            ))}
          </div>
        )}
        <p className="muted" style={{ marginTop: 12 }}>↻ Re-validated against all engines after each approved fix — only re-passing files advance to publish.</p>
      </section>
      {selItem && <ReviewDrawer item={selItem} onClose={() => setSelItem(null)} onAct={act} />}
    </>
  )
}

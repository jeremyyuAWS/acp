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
  const [self, setSelf] = useState([])
  const act = (id, kind) => {
    const item = queue.find((x) => x.id === id)
    setQueue((q) => q.filter((x) => x.id !== id))
    setSelItem(null)
    if (kind === 'self') { if (item) setSelf((s) => [{ ...item, status: 'awaiting' }, ...s]); return }
    setActed((a) => ({ ...a, [kind]: a[kind] + 1 }))
  }
  const rescan = (id) => {
    setSelf((s) => s.map((x) => x.id === id ? { ...x, status: 'scanning' } : x))
    setTimeout(() => setSelf((s) => s.map((x) => x.id === id ? { ...x, status: 'verified' } : x)), 1700)
  }
  const verified = self.filter((x) => x.status === 'verified').length

  return (
    <>
      <div className="metrics">
        <div className="metric"><span>auto-fixed issues</span><b style={{ color: '#3B6D11' }}>{autoFixed}</b></div>
        <div className="metric"><span>in review queue</span><b style={{ color: '#854F0B' }}>{queue.length}</b></div>
        <div className="metric"><span>approved</span><b>{acted.approved}</b></div>
        <div className="metric"><span>self-remediated</span><b style={{ color: '#185FA5' }}>{self.length}</b></div>
        <div className="metric"><span>re-verified</span><b style={{ color: '#3B6D11' }}>{verified}</b></div>
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
                <button className="qbtn self" onClick={(e) => { e.stopPropagation(); act(q.id, 'self') }} title="Take ownership — fix it yourself, then re-scan to confirm">✋ I’ll fix it</button>
                <button className="qbtn reject" onClick={(e) => { e.stopPropagation(); act(q.id, 'rejected') }}>✕ reject</button>
              </div>
            ))}
          </div>
        )}
        <p className="muted" style={{ marginTop: 12 }}>↻ Re-validated against all engines after each approved fix — only re-passing files advance to publish.</p>
      </section>

      {self.length > 0 && (
        <section className="panel">
          <h2>Self-remediation <span className="muted">· you’re fixing these — re-scan to confirm</span></h2>
          <div className="queue">
            {self.map((it) => (
              <div className={`qrow${it.status === 'verified' ? ' qdone' : ''}`} key={it.id}>
                <span className="qico" aria-hidden="true">{it.icon}</span>
                <div className="qmain">
                  <div className="qtitle">{it.title} <span className="muted" style={{ fontSize: 12 }}>· {it.file}</span></div>
                  <div className="qmeta">{it.rule}</div>
                  <div className="selfstatus">
                    {it.status === 'awaiting' && <span className="muted">awaiting your fix — apply it in the source, then confirm</span>}
                    {it.status === 'scanning' && <span className="muted"><span className="spinner" /> re-scanning across all engines…</span>}
                    {it.status === 'verified' && <span className="okline">✓ verified — finding cleared, now passing 100 / 100</span>}
                  </div>
                </div>
                {it.status === 'verified'
                  ? <span className="qbtn verified">✓ confirmed</span>
                  : <button className="qbtn rescan" disabled={it.status === 'scanning'} onClick={() => rescan(it.id)}>↻ Re-scan to confirm</button>}
              </div>
            ))}
          </div>
          <p className="muted" style={{ marginTop: 12 }}>When you remediate a document yourself, the agent re-runs every engine to independently confirm the fix before it’s certified — no manual sign-off taken on trust.</p>
        </section>
      )}
      {selItem && <ReviewDrawer item={selItem} onClose={() => setSelItem(null)} onAct={act} />}
    </>
  )
}

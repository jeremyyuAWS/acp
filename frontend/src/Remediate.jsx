import { useState, useEffect } from 'react'
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
// Rotating gallery of real fix examples across formats — replaces the old static
// before/after so it visibly changes and shows the agent working on each type.
const FIX_EXAMPLES = [
  { fmt: 'PDF', wcag: 'WCAG 1.1.1 · alt text', auto: true, before: 'figure 3 — no alt text', after: 'alt: “Q3 benefits enrollment by region — West 38%, NE 24%, South 22%, Midwest 16%”' },
  { fmt: 'Video', wcag: 'WCAG 1.2.2 · captions', auto: false, before: '4:12 video — no caption track', after: 'Synchronized captions drafted (speech-to-text) — pending human review' },
  { fmt: 'Excel', wcag: 'WCAG 1.3.1 · table headers', auto: true, before: 'merged cells A1:C1, no header row', after: 'header row tagged <th scope="col"> so structure is announced' },
  { fmt: 'Web', wcag: 'WCAG 1.4.3 · contrast', auto: false, before: 'body text at 3.1:1 on grey', after: 'recoloured to 4.8:1 — now passes AA (design-reviewed)' },
  { fmt: 'Audio', wcag: 'WCAG 1.2.1 · transcript', auto: false, before: 'podcast episode — no transcript', after: 'transcript drafted from speech-to-text — pending human review' },
]
const QUEUE0 = [
  { id: 1, icon: '▦', title: 'chart on slide 7 — alt-text', meta: 'suggested alt-text', conf: 61, file: 'open-enrollment-deck.pptx', rule: 'WCAG 1.1.1 — non-text content',
    before: '<pic alt="">', after: '<pic alt="Q3 revenue by region — West 38%, NE 24%, South 22%, Midwest 16%">' },
  { id: 2, icon: '⊞', title: 'merged cells — table headers', meta: 'needs a human structure call', conf: 48, file: 'budget-model.xlsx', rule: 'WCAG 1.3.1 — info & relationships',
    before: '<table> — merged A1:C1, no header row', after: '<table> — unmerged, <th scope="col"> on row 1' },
  { id: 3, icon: '¶', title: 'reading order — multi-column page', meta: 'two plausible orders', conf: 55, file: 'annual-report-2025.pdf', rule: 'WCAG 1.3.2 — meaningful sequence',
    before: 'tab order: right column before left', after: 'tab order: left column → right (natural)' },
  { id: 4, icon: '◫', title: 'scanned page — needs OCR + tags', meta: 'low text confidence', conf: 42, file: 'vendor-contract-acme.pdf', rule: 'WCAG 1.3.1 — info & relationships',
    note: 'Image-only PDF — the agent recommends OCR + manual tagging before this can be certified; no auto-fix proposed.' },
  { id: 5, icon: '🎬', title: 'video captions — AI draft ready', meta: 'ASR captions need review', conf: 58, file: 'patient-explainer.mp4', rule: 'WCAG 1.2.2 — captions',
    before: '4:12 video — no caption track', after: 'Synchronized captions drafted (speech-to-text) — review timing & accuracy' },
]

function FixCarousel() {
  const [idx, setIdx] = useState(0)
  const [paused, setPaused] = useState(false)
  useEffect(() => {
    if (paused) return
    const t = setInterval(() => setIdx((i) => (i + 1) % FIX_EXAMPLES.length), 3800)
    return () => clearInterval(t)
  }, [paused])
  const ex = FIX_EXAMPLES[idx]
  return (
    <section className="panel" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
      <div className="fixhd">
        <h2 style={{ margin: 0 }}>AI remediation · live <span className="livedot" aria-hidden="true" /></h2>
        <span className="muted" style={{ fontSize: 12 }}>{idx + 1} / {FIX_EXAMPLES.length}</span>
      </div>
      <div className="fixcard" key={idx}>
        <div className="fixmeta">
          <span className="fmtchip">{ex.fmt}</span>
          <span className="muted" style={{ fontSize: 12 }}>{ex.wcag}</span>
          <span className={ex.auto ? 'fixauto' : 'fixreview'} style={{ marginLeft: 'auto', fontSize: 12 }}>{ex.auto ? '⚡ auto-applied' : '✎ AI draft · human review'}</span>
        </div>
        <div className="diffbox before"><span className="difftag">before</span>{ex.before}</div>
        <div className="diffbox after"><span className="difftag">after</span>{ex.after}</div>
      </div>
      <div className="fixdots">
        {FIX_EXAMPLES.map((_, i) => <button key={i} className={i === idx ? 'fixdot on' : 'fixdot'} aria-label={`example ${i + 1}`} onClick={() => setIdx(i)} />)}
      </div>
    </section>
  )
}

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
        <FixCarousel />
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

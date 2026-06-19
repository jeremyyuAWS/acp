import { useState, useEffect } from 'react'
import { Bars } from './charts.jsx'
import ReviewDrawer from './ReviewDrawer.jsx'
import FileDrawer, { REC_STYLE, fmtEffort } from './FileDrawer.jsx'
import SegmentDrawer from './SegmentDrawer.jsx'
import { recommendationSummary, SENIORITY_ORDER, REMEDIATION_ACTIONS } from './sim.js'
import { prefersReducedMotion } from './a11y.js'

// Steps 6-8: Automated Remediation + HITL + Re-validate. Owns the remediation plan
// (what to fix, prioritized, accept/reject/modify), the HITL queue, and self-remediation.
const REM_ACTIONS = REMEDIATION_ACTIONS
const SUBS = [['auto', '6 · Auto-remediate'], ['review', '7 · Human review'], ['revalidate', '8 · Re-validate']]
const ACTIONS = ['auto', 'assisted', 'review', 'archive', 'keep', 'manual']
const ETA_OVERRIDE = { archive: 2, keep: 0, manual: 35, review: 10 }
const hrs = (m) => m >= 90 ? `${(m / 60).toFixed(1)} hrs` : `${Math.round(m)} min`
const ACTION_DESC = {
  auto: 'The agent fixes these mechanically — alt text, headings, language, titles — then re-validates. No human needed.',
  assisted: 'AI proposes the fix; a human approves before publish. For critical, sensitive, contrast/link, or media (captions) findings.',
  review: 'A rule couldn’t be auto-evaluated. A reviewer confirms before the document can be certified.',
  manual: 'Unreadable source — a human must re-author or re-export the file before it can be assessed.',
}
const SR_COLOR = { Executive: '#A32D2D', Director: '#D85A30', Manager: '#F5B400', Staff: '#9a948f' }
const exposureOf = (f) => (f.tags || []).includes('public-facing') ? 'public-facing' : (f.tags || []).includes('high-traffic') ? 'high-traffic' : 'internal'
const EXP_COLOR = { 'public-facing': '#A32D2D', 'high-traffic': '#D85A30', internal: '#9a948f' }
const SR_W = { Executive: 3, Director: 2, Manager: 1, Staff: 0 }
const priority = (f) => (f.tags || []).filter((t) => t === 'public-facing' || t === 'high-traffic').length * 2 + (SR_W[f.seniority] || 0) + (f.issues || []).filter((i) => i.severity === 'CRITICAL').length * 2

const FIX_TYPES = [
  { label: 'alt-text generated', value: 38, color: '#639922' },
  { label: 'reading order fixed', value: 21, color: '#1D9E75' },
  { label: 'headings tagged', value: 14, color: '#378ADD' },
  { label: 'language set', value: 9, color: '#7F77DD' },
  { label: 'table headers', value: 6, color: '#BA7517' },
]
const FIX_EXAMPLES = [
  { fmt: 'PDF', wcag: 'WCAG 1.1.1 · alt text', auto: true, before: 'figure 3 — no alt text', after: 'alt: “Q3 benefits enrollment by region — West 38%, NE 24%, South 22%, Midwest 16%”' },
  { fmt: 'Video', wcag: 'WCAG 1.2.2 · captions', auto: false, before: '4:12 video — no caption track', after: 'Synchronized captions drafted (speech-to-text) — pending human review' },
  { fmt: 'Excel', wcag: 'WCAG 1.3.1 · table headers', auto: true, before: 'merged cells A1:C1, no header row', after: 'header row tagged <th scope="col"> so structure is announced' },
  { fmt: 'Web', wcag: 'WCAG 1.4.3 · contrast', auto: false, before: 'body text at 3.1:1 on grey', after: 'recoloured to 4.8:1 — now passes AA (design-reviewed)' },
  { fmt: 'Audio', wcag: 'WCAG 1.2.1 · transcript', auto: false, before: 'podcast episode — no transcript', after: 'transcript drafted from speech-to-text — pending human review' },
]
const QUEUE0 = [
  { id: 1, icon: '▦', title: 'chart on slide 7 — alt-text', meta: 'suggested alt-text', conf: 61, file: 'open-enrollment-deck.pptx', rule: 'WCAG 1.1.1 — non-text content', before: '<pic alt="">', after: '<pic alt="Q3 revenue by region — West 38%, NE 24%, South 22%, Midwest 16%">' },
  { id: 2, icon: '⊞', title: 'merged cells — table headers', meta: 'needs a human structure call', conf: 48, file: 'budget-model.xlsx', rule: 'WCAG 1.3.1 — info & relationships', before: '<table> — merged A1:C1, no header row', after: '<table> — unmerged, <th scope="col"> on row 1' },
  { id: 3, icon: '¶', title: 'reading order — multi-column page', meta: 'two plausible orders', conf: 55, file: 'annual-report-2025.pdf', rule: 'WCAG 1.3.2 — meaningful sequence', before: 'tab order: right column before left', after: 'tab order: left column → right (natural)' },
  { id: 4, icon: '◫', title: 'scanned page — needs OCR + tags', meta: 'low text confidence', conf: 42, file: 'vendor-contract-acme.pdf', rule: 'WCAG 1.3.1 — info & relationships', note: 'Image-only PDF — the agent recommends OCR + manual tagging before this can be certified; no auto-fix proposed.' },
  { id: 5, icon: '🎬', title: 'video captions — AI draft ready', meta: 'ASR captions need review', conf: 58, file: 'patient-explainer.mp4', rule: 'WCAG 1.2.2 — captions', before: '4:12 video — no caption track', after: 'Synchronized captions drafted (speech-to-text) — review timing & accuracy' },
]

function FixCarousel() {
  const [idx, setIdx] = useState(0)
  const [paused, setPaused] = useState(false)
  useEffect(() => {
    if (paused || prefersReducedMotion()) return
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

export default function Remediate({ run, files = [], decisions = {}, setDecisions }) {
  const autoFixed = FIX_TYPES.reduce((a, f) => a + f.value, 0)
  const [queue, setQueue] = useState(QUEUE0)
  const [acted, setActed] = useState({ approved: 0, rejected: 0 })
  const [selItem, setSelItem] = useState(null)
  const [self, setSelf] = useState([])
  const [sel, setSel] = useState(null)
  const [seg, setSeg] = useState(null)
  const [editing, setEditing] = useState(null)
  const [sub, setSub] = useState('auto')
  const revalidated = files.filter((f) => f.compliant)

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

  // --- remediation plan + decisions (moved from Discover) ---
  const plan = files.length ? recommendationSummary(files) : null
  const planCards = plan ? plan.buckets.filter((b) => REM_ACTIONS.includes(b.action)) : []
  const remediable = files.filter((f) => f.rec && REM_ACTIONS.includes(f.rec.action)).sort((a, b) => priority(b) - priority(a))
  const decide = (file, d) => { setDecisions?.((s) => ({ ...s, [file]: d })); setEditing(null) }
  const undo = (file) => setDecisions?.((s) => { const n = { ...s }; delete n[file]; return n })
  const acceptAll = () => setDecisions?.((s) => { const n = { ...s }; remediable.forEach((f) => { if (!n[f.file]) n[f.file] = { state: 'accepted' } }); return n })
  const dcount = (st) => remediable.filter((f) => decisions[f.file]?.state === st).length
  const pending = remediable.length - dcount('accepted') - dcount('override') - dcount('rejected')

  // business priority (findings-based)
  const flagged = files.filter((f) => (f.issues || []).length)
  const findingsBy = (keyFn, order) => {
    const m = {}; flagged.forEach((f) => { const k = keyFn(f); if (k != null) m[k] = (m[k] || 0) + f.issues.length })
    return (order ? order.filter((k) => m[k]).map((k) => [k, m[k]]) : Object.entries(m).sort((a, b) => b[1] - a[1]))
  }
  const deptData = findingsBy((f) => f.department).slice(0, 8).map(([label, value]) => ({ label, value, color: '#7a5c8e' }))
  const senData = findingsBy((f) => f.seniority, SENIORITY_ORDER).map(([label, value]) => ({ label, value, color: SR_COLOR[label] }))
  const expData = findingsBy(exposureOf, ['public-facing', 'high-traffic', 'internal']).map(([label, value]) => ({ label, value, color: EXP_COLOR[label] }))
  const pubCrit = flagged.filter((f) => (f.tags || []).includes('public-facing') && (f.issues || []).some((i) => i.severity === 'CRITICAL')).length
  const execFlagged = flagged.filter((f) => f.seniority === 'Executive').length
  const drill = (title, sub, pred) => setSeg({ title, subtitle: sub, files: flagged.filter(pred) })

  return (
    <>
      <div className="metrics">
        <div className="metric"><span>auto-fixed issues</span><b style={{ color: '#3B6D11' }}>{autoFixed}</b></div>
        <div className="metric"><span>in review queue</span><b style={{ color: '#854F0B' }}>{queue.length}</b></div>
        <div className="metric"><span>approved</span><b>{acted.approved}</b></div>
        <div className="metric"><span>self-remediated</span><b style={{ color: '#185FA5' }}>{self.length}</b></div>
        <div className="metric"><span>re-verified</span><b style={{ color: '#3B6D11' }}>{verified}</b></div>
      </div>

      <div className="subtabs" role="tablist" aria-label="Remediate steps">
        {SUBS.map(([k, label]) => <button key={k} role="tab" aria-selected={sub === k} className={sub === k ? 'fchip on' : 'fchip'} onClick={() => setSub(k)}>{label}</button>)}
      </div>

      {sub === 'auto' && (<>
      {plan && (
        <div className="planband">
          <div className="planhead">
            <div>
              <b>Remediation plan</b>
              <div className="muted" style={{ marginTop: 2 }}>
                ≈ <b style={{ color: 'var(--ink)' }}>{hrs(plan.remediateMin)}</b> across {plan.remediableDocs} documents · <b style={{ color: '#3B6D11' }}>{plan.autoPct}% fully automatic</b> · saves ≈ <b style={{ color: '#3B6D11' }}>{hrs(plan.savedMin)}</b> vs. manual
              </div>
            </div>
            <div className="plandec">
              <span className="muted">{dcount('accepted')} accepted · {dcount('override')} modified · {dcount('rejected')} rejected · {pending} pending</span>
              <button disabled={!pending} onClick={acceptAll}>✓ Accept all</button>
            </div>
          </div>
          <div className="plancards">
            {planCards.map((b) => {
              const [label, bg, fg, icon] = REC_STYLE[b.action] || REC_STYLE.review
              return (
                <div className="plancard" key={b.action} style={{ background: bg }} tabIndex={0} aria-label={`${label}: ${ACTION_DESC[b.action]}`}>
                  <div className="plancardtop" style={{ color: fg }}><span>{icon}</span><b>{b.n}</b></div>
                  <div className="plancardlbl" style={{ color: fg }}>{label}</div>
                  <div className="muted plancardeta">{b.action === 'manual' ? `~${hrs(b.min)} manual` : `~${hrs(b.min)}`}</div>
                  <div className="plantip" role="tooltip"><b style={{ color: fg }}>{icon} {label}</b>{ACTION_DESC[b.action]}</div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {flagged.length > 0 && (
        <div className="prioritypanel">
          <div className="priorityhd"><b>Business priority</b> <span className="muted">· what to fix first — weighted by exposure, severity &amp; ownership</span></div>
          <div className="prioritynote">⚑ {pubCrit} public-facing document{pubCrit === 1 ? '' : 's'} ha{pubCrit === 1 ? 's' : 've'} critical findings and {execFlagged} are executive-owned — the highest business risk under ADA / EAA. Start here.</div>
          <div className="prioritygrid">
            <section className="ppanel"><h3>Open findings by department</h3><Bars items={deptData} cols="118px 1fr 28px" onPick={(it) => drill(`${it.label} · open findings`, `${it.value} findings`, (f) => f.department === it.label)} /></section>
            <section className="ppanel"><h3>By owner seniority</h3><Bars items={senData} cols="92px 1fr 28px" onPick={(it) => drill(`${it.label}-owned · open findings`, `${it.value} findings`, (f) => f.seniority === it.label)} /><div className="muted ppfoot">executive / director-owned content carries more reputational weight</div></section>
            <section className="ppanel"><h3>By exposure</h3><Bars items={expData} cols="98px 1fr 28px" onPick={(it) => drill(`${it.label} · open findings`, `${it.value} findings`, (f) => exposureOf(f) === it.label)} /><div className="muted ppfoot">public-facing pages are the top legal-exposure set</div></section>
          </div>
        </div>
      )}

      {remediable.length > 0 && (
        <section className="panel">
          <h2>Documents to remediate <span className="muted">· {remediable.length}, highest priority first — accept / reject / modify the agent’s plan</span></h2>
          <div className="remlist">
            {remediable.map((f) => {
              const rec = f.rec; const dec = decisions[f.file]
              const effAction = dec?.state === 'override' ? dec.action : rec.action
              const [label, rbg, rfg, icon] = REC_STYLE[effAction] || REC_STYLE.review
              const effEta = dec?.state === 'override' ? (ETA_OVERRIDE[dec.action] ?? rec.etaMin) : rec.etaMin
              return (
                <div className={`remrow${dec?.state === 'rejected' ? ' rowrej' : ''}`} key={f.file} style={{ borderLeft: `3px solid ${rfg}`, paddingLeft: 10 }}>
                  <button className="remname" onClick={() => setSel(f)}>{f.file}<span className="muted"> · {f.sourceName} · {f.department}</span></button>
                  <span className="reccell">
                    <span className="badge" style={{ background: rbg, color: rfg }}>{icon} {label}</span>
                    {dec?.state === 'accepted' && <span className="dectag ok">✓ accepted</span>}
                    {dec?.state === 'override' && <span className="dectag ov">modified</span>}
                    {dec?.state === 'rejected' && <span className="dectag rj">rejected</span>}
                    {editing === f.file ? (
                      <span className="modchips">
                        {ACTIONS.map((a) => { const [l, , fg, ic] = REC_STYLE[a]; return <button key={a} className="modchip" style={{ color: fg }} onClick={() => decide(f.file, a === rec.action ? { state: 'accepted' } : { state: 'override', action: a })}>{ic} {l}</button> })}
                        <button className="modchip cancel" onClick={() => setEditing(null)}>cancel</button>
                      </span>
                    ) : (
                      <span className="decctl">
                        {!dec ? (<>
                          <button className="decbtn ok" title="Accept" onClick={() => decide(f.file, { state: 'accepted' })}>✓</button>
                          <button className="decbtn rj" title="Reject" onClick={() => decide(f.file, { state: 'rejected' })}>✕</button>
                          <button className="decbtn ed" title="Modify action" onClick={() => setEditing(f.file)}>✎</button>
                        </>) : <button className="decbtn undo" title="Undo" onClick={() => undo(f.file)}>↺</button>}
                      </span>
                    )}
                  </span>
                  <span className="etacell">{fmtEffort(effEta)}</span>
                </div>
              )
            })}
          </div>
        </section>
      )}

      <div className="chartrow">
        <section className="panel"><h2>Automated fixes applied · by type</h2><Bars items={FIX_TYPES} cols="140px 1fr 30px" /></section>
        <FixCarousel />
      </div>
      </>)}

      {sub === 'review' && (<>
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
      </>)}

      {sub === 'revalidate' && (
        <>
          <section className="panel"><h2>Re-validate &amp; verify</h2>
            <div className="lift" style={{ margin: '8px 0 12px' }}>
              <div className="liftcol"><div className="liftnum" style={{ color: '#A32D2D' }}>{run?.avg_score ?? 72}</div><div className="muted">before</div></div>
              <div className="liftarrow" aria-hidden="true">→</div>
              <div className="liftcol"><div className="liftnum" style={{ color: '#3B6D11' }}>{Math.min(100, (run?.avg_score ?? 72) + 12)}</div><div className="muted">after re-validation</div></div>
              <div className="liftgain">+{Math.min(100, (run?.avg_score ?? 72) + 12) - (run?.avg_score ?? 72)} pts</div>
            </div>
            <p className="muted">Every approved or self-applied fix is re-run against all engines. Only documents that re-pass advance to Publish — no fix is taken on trust.</p>
          </section>
          <section className="panel"><h2>Re-validated &amp; ready to publish <span className="muted">· {revalidated.length}</span></h2>
            {revalidated.length === 0 ? <p className="muted">None yet — approve fixes in the review step first.</p> : (
              <div className="publist">
                {revalidated.slice(0, 40).map((f) => (
                  <div className="pubrow" key={f.file}>
                    <button className="remname" onClick={() => setSel(f)}>{f.file}<span className="muted"> · {f.sourceName}</span></button>
                    <span className="okline" style={{ fontSize: 13 }}>✓ verified {f.score} / 100 — advances to Publish</span>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {seg && <SegmentDrawer title={seg.title} subtitle={seg.subtitle} files={seg.files} onClose={() => setSeg(null)} onPickFile={(f) => { setSeg(null); setSel(f) }} />}
      {sel && <FileDrawer file={sel} onClose={() => setSel(null)} />}
      {selItem && <ReviewDrawer item={selItem} onClose={() => setSelItem(null)} onAct={act} />}
    </>
  )
}

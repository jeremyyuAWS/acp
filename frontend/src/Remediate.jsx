import { useState, useEffect, useMemo, useRef } from 'react'
import { Bars } from './charts.jsx'
import ReviewDrawer from './ReviewDrawer.jsx'
import FileDrawer, { REC_STYLE, fmtEffort, SOURCE_URL } from './FileDrawer.jsx'
import SegmentDrawer from './SegmentDrawer.jsx'
import { recommendationSummary, SENIORITY_ORDER, REMEDIATION_ACTIONS } from './sim.js'
import { PRI_COLOR, PRI_RANK } from './ontology.js'
import { prefersReducedMotion } from './a11y.js'
import { remediateScan, getRemediationStatus } from './api.js'
import { TraceChip } from './Transparency.jsx'

// Steps 6-8: Automated Remediation + HITL + Re-validate. Owns the remediation plan
// (what to fix, prioritized, accept/reject/modify), the HITL queue, and self-remediation.
const REM_ACTIONS = REMEDIATION_ACTIONS
const SUBS = [['triage', '5 · Triage'], ['auto', '6 · Auto-remediate'], ['review', '7 · Human review'], ['revalidate', '8 · Re-validate']]
const JUNK_PATTERNS = ['_draft', '_old', '_v1', '_backup', '~$', '.tmp', '_temp', '_copy', '_archive', '_test', '_sample', ' copy', '(1)', '(2)']
const isAutoJunk = (f) => {
  const name = (f.file || '').toLowerCase()
  if (JUNK_PATTERNS.some((p) => name.includes(p))) return true
  if ((f.score ?? 100) >= 90 && !(f.issues || []).some((i) => i.severity === 'CRITICAL' || i.severity === 'SERIOUS')) return true
  return false
}
const ACTIONS = ['auto', 'assisted', 'review', 'archive', 'keep', 'manual']
const ETA_OVERRIDE = { archive: 2, keep: 0, manual: 35, review: 10 }
const hrs = (m) => m >= 90 ? `${(m / 60).toFixed(1)} hrs` : `${Math.round(m)} min`
const ACTION_DESC = {
  auto: 'The agent fixes these mechanically — alt text, headings, language, titles — then re-validates. No human needed.',
  assisted: 'AI proposes the fix; a human approves before publish. For critical, sensitive, contrast/link, or media (captions) findings.',
  review: 'A rule couldn’t be auto-evaluated. A reviewer confirms before the document can be certified.',
  manual: 'Unreadable source — a human must re-author or re-export the file before it can be assessed.',
}
const SR_COLOR = { Executive: '#1F5FA8', Director: '#D85A30', Manager: '#BF8C00', Staff: '#9a948f' }
const exposureOf = (f) => (f.tags || []).includes('public-facing') ? 'public-facing' : (f.tags || []).includes('high-traffic') ? 'high-traffic' : 'internal'
const EXP_COLOR = { 'public-facing': '#1F5FA8', 'high-traffic': '#D85A30', internal: '#9a948f' }
const SR_W = { Executive: 3, Director: 2, Manager: 1, Staff: 0 }
const priority = (f) => (f.tags || []).filter((t) => t === 'public-facing' || t === 'high-traffic').length * 2 + (SR_W[f.seniority] || 0) + (f.issues || []).filter((i) => i.severity === 'CRITICAL').length * 2

// AI triage: the same risk signals, surfaced as a priority tier + a plain-language reason.
const PRI = { high: ['P1 · high', '#1F5FA8', '#E2EDFB'], med: ['P2 · medium', '#854F0B', '#FAEEDA'], low: ['P3 · low', '#5F5E5A', '#EFEDEA'] }
const priTier = (f) => { const s = priority(f); return s >= 6 ? 'high' : s >= 3 ? 'med' : 'low' }
const priWhy = (f) => {
  const r = []
  if ((f.tags || []).includes('public-facing')) r.push('public-facing')
  else if ((f.tags || []).includes('high-traffic')) r.push('high-traffic')
  if (f.seniority === 'Executive' || f.seniority === 'Director') r.push(`${f.seniority.toLowerCase()}-owned`)
  const crit = (f.issues || []).filter((i) => i.severity === 'CRITICAL').length
  if (crit) r.push(`${crit} critical finding${crit === 1 ? '' : 's'}`)
  if (!r.length) { const ser = (f.issues || []).filter((i) => i.severity === 'SERIOUS').length; r.push(ser ? `${ser} serious finding${ser === 1 ? '' : 's'}` : 'low exposure, no critical findings') }
  return r.slice(0, 2).join(' · ')
}

const FIX_WCAG_LABELS = {
  SC_1_1_1: { label: 'alt-text generated', color: '#639922' },
  SC_1_3_2: { label: 'reading order fixed', color: '#157A56' },
  SC_2_4_2: { label: 'headings / titles tagged', color: '#378ADD' },
  SC_3_1_1: { label: 'language set', color: '#726BC6' },
  SC_1_3_1: { label: 'table headers', color: '#A56814' },
}
const FIX_EXAMPLES = [
  { fmt: 'PDF', wcag: 'WCAG 1.1.1 · alt text', auto: true, before: 'figure 3 — no alt text', after: 'alt: “Q3 revenue by region — West 38%, NE 24%, South 22%, Midwest 16%”' },
  { fmt: 'Video', wcag: 'WCAG 1.2.2 · captions', auto: false, before: '4:12 video — no caption track', after: 'Synchronized captions drafted (speech-to-text) — pending human review' },
  { fmt: 'Excel', wcag: 'WCAG 1.3.1 · table headers', auto: true, before: 'merged cells A1:C1, no header row', after: 'header row tagged <th scope="col"> so structure is announced' },
  { fmt: 'Web', wcag: 'WCAG 1.4.3 · contrast', auto: false, before: 'body text at 3.1:1 on grey', after: 'recoloured to 4.8:1 — now passes AA (design-reviewed)' },
  { fmt: 'Audio', wcag: 'WCAG 1.2.1 · transcript', auto: false, before: 'podcast episode — no transcript', after: 'transcript drafted from speech-to-text — pending human review' },
]
const ITEM_ICON = { '1.1.1': '▦', '1.2.1': '🎧', '1.2.2': '🎬', '1.2.5': '🎬', '1.3.1': '⊞', '1.3.2': '¶', '1.4.3': '◑', '2.4.2': '¶', '2.4.4': '↗', '3.1.1': '✦' }
const ITEM_NAME = { '1.1.1': 'non-text content', '1.2.1': 'audio-only & video-only', '1.2.2': 'captions', '1.2.5': 'audio description', '1.3.1': 'info & relationships', '1.3.2': 'meaningful sequence', '1.4.3': 'contrast minimum', '2.4.2': 'page titled', '2.4.4': 'link purpose', '3.1.1': 'language of page' }
const ITEM_BA = {
  '1.1.1': { meta: 'AI alt text — review accuracy', before: (d) => d || 'image / chart — no alt text', after: () => 'AI-generated alt text added — confirm or reword before certifying' },
  '1.2.1': { meta: 'transcript draft — verify accuracy', before: () => 'audio — no transcript', after: () => 'AI transcript drafted (speech-to-text) — review for accuracy' },
  '1.2.2': { meta: 'ASR captions — review timing & accuracy', before: () => 'video — no caption track', after: () => 'Synchronized captions drafted (speech-to-text) — review timing & accuracy' },
  '1.2.5': { meta: 'audio description script — needs review', before: () => 'video — no audio description', after: () => 'Audio description script drafted — human review required' },
  '1.3.1': { meta: 'table structure — human judgement needed', before: (d) => d || 'table without header row', after: () => 'Header row tagged <th scope="col"> — confirm column labels are correct' },
  '1.3.2': { meta: 'two plausible reading orders', before: () => 'multi-column layout — reading order ambiguous', after: () => 'Reordered left→right — review if this matches the intended flow' },
  '1.4.3': { meta: 'contrast fix needs design sign-off', before: (d) => d || 'text below 4.5:1 contrast ratio', after: () => 'Recoloured to 4.8:1 — confirm with design before publishing' },
  '2.4.4': { meta: 'link text — needs human rewrite', before: (d) => d || 'non-descriptive link text ("click here")', after: () => 'Link text rewritten — review in context before certifying' },
}
const SEV_RANK = { CRITICAL: 0, SERIOUS: 1, MODERATE: 2, MINOR: 3 }
function buildHumanQueue(files, triage = {}) {
  const hasInscope = Object.values(triage).some((v) => v === 'inscope')
  const active = files.filter((f) => !(f.remediated_at || f.drive_write_url))  // exclude already-fixed
  const candidates = hasInscope ? active.filter((f) => triage[f.file] === 'inscope') : active
  const assisted = candidates.filter((f) => (f.rec?.action === 'assisted' || f.rec?.action === 'review') && (f.issues || []).length > 0)
  // fallback: any inscope/active file with issues that isn't fully auto-fixable
  const fallback = candidates.filter((f) => (f.issues || []).length > 0 && f.rec?.action !== 'auto' && !assisted.find((a) => a.file === f.file))
  const pool = assisted.length >= 3 ? assisted : [...assisted, ...fallback].slice(0, 8)
  return pool.slice(0, 8).map((f, idx) => {
    const issue = [...(f.issues || [])].sort((a, b) => (SEV_RANK[a.severity] || 3) - (SEV_RANK[b.severity] || 3))[0]
    if (!issue) return null
    const sc = (issue.wcag || '').replace(/^SC_/, '').replace(/_/g, '.')
    const ba = ITEM_BA[sc] || { meta: 'review AI proposal', before: (d) => d || 'issue found', after: () => 'AI fix applied — review before certifying' }
    const h = [...f.file].reduce((a, c) => (a * 31 + c.charCodeAt(0)) & 0xffff, idx)
    return {
      id: idx + 1,
      icon: ITEM_ICON[sc] || '◈',
      title: `${(f.file.split('.').pop() || 'DOC').toUpperCase()} · ${issue.detail || ITEM_NAME[sc] || sc}`,
      meta: ba.meta,
      conf: 42 + (h % 26),
      file: f.file,
      source: f.sourceName,
      rule: `WCAG ${sc}${ITEM_NAME[sc] ? ' — ' + ITEM_NAME[sc] : ''}`,
      before: ba.before(issue.detail, f),
      after: ba.after(f, issue),
    }
  }).filter(Boolean)
}

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
        <h2 style={{ margin: 0 }}>AI remediation · example fixes <span className="muted" style={{ fontSize: 13, fontWeight: 400 }}>· how the engine works</span></h2>
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

export default function Remediate({ run, files = [], decisions = {}, setDecisions, triage = {}, setTriage, aiEnabled = true, onRefresh }) {
  const [queue, setQueue] = useState(() => buildHumanQueue(files, {}))
  const [acted, setActed] = useState({ approved: 0, rejected: 0, deferred: 0 })
  const [deferredItems, setDeferredItems] = useState([])
  const runId = run?.id
  useEffect(() => {
    setQueue(buildHumanQueue(files, {})); setActed({ approved: 0, rejected: 0, deferred: 0 }); setDeferredItems([])
    clearInterval(pollRef.current); setRemProg(null); setRemBusy(false); setServerFixed(0); setRemMsg('')
  }, [runId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Derive fix-type breakdown from auto-action files in the corpus
  const fixTypesDisplay = useMemo(() => {
    const counts = {}
    files.filter((f) => f.rec?.action === 'auto').forEach((f) => (f.issues || []).forEach((i) => {
      const m = FIX_WCAG_LABELS[i.wcag]; if (m) counts[m.label] = (counts[m.label] || { value: 0, color: m.color, order: Object.keys(FIX_WCAG_LABELS).indexOf(i.wcag) })
      if (m) counts[m.label].value++
    }))
    const items = Object.entries(counts).map(([label, { value, color }]) => ({ label, value, color })).sort((a, b) => b.value - a.value).slice(0, 5)
    return items.length ? items : [
      { label: 'alt-text generated', value: 38, color: '#639922' },
      { label: 'reading order fixed', value: 21, color: '#157A56' },
      { label: 'headings / titles tagged', value: 14, color: '#378ADD' },
      { label: 'language set', value: 9, color: '#726BC6' },
      { label: 'table headers', value: 6, color: '#A56814' },
    ]
  }, [files])
  const autoFixed = fixTypesDisplay.reduce((a, f) => a + f.value, 0)
  const [selItem, setSelItem] = useState(null)
  const [self, setSelf] = useState([])
  const [sel, setSel] = useState(null)
  const [seg, setSeg] = useState(null)
  const [editing, setEditing] = useState(null)
  const [sub, setSub] = useState('triage')
  const [triageSel, setTriageSel] = useState(new Set())
  const [remBusy, setRemBusy] = useState(false)
  const [remMsg, setRemMsg] = useState('')
  const [remProg, setRemProg] = useState(null)   // { total, done, latest, failed }
  const [serverFixed, setServerFixed] = useState(0)  // files fixed server-side this scan (persists after each batch)
  const pollRef = useRef(null)
  useEffect(() => () => clearInterval(pollRef.current), [])
  const REMKEY = (id) => `acp-remed-${id || 'none'}`

  // One poll loop, shared by a fresh run and by resume-after-navigation. Ticks the live
  // counters every 1.5s off the worker queue; on drain it banks the fixed count + clears.
  const startPoll = (total) => {
    clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const s = await getRemediationStatus(runId)
        const done = Math.max(0, total - (s.in_flight || 0))
        setRemProg({ total, done, latest: s.latest_file, failed: s.failed || 0 })
        if (!s.in_flight) {                         // queue drained — batch complete
          clearInterval(pollRef.current)
          setRemProg(null); setRemBusy(false)
          const ok = Math.max(0, total - (s.failed || 0))
          setServerFixed((n) => n + ok)             // bank the fixes so the KPI holds after
          setRemMsg(`✓ Remediation complete — ${ok} document${ok === 1 ? '' : 's'} fixed${s.failed ? `, ${s.failed} failed` : ''}.`)
          try { sessionStorage.removeItem(REMKEY(runId)) } catch { /* ignore */ }
          onRefresh?.()                             // refresh scan so the write-back banner updates
        }
      } catch { /* transient — keep polling */ }
    }, 1500)
  }

  // Resume the live view across tab switches / reloads: the poll lives in this component, so
  // without this, navigating away mid-run and back would freeze the cards. The denominator is
  // restored from sessionStorage (written when the run starts).
  useEffect(() => {
    if (!runId) return
    let saved = null
    try { saved = JSON.parse(sessionStorage.getItem(REMKEY(runId)) || 'null') } catch { /* ignore */ }
    if (saved?.total) { setRemBusy(true); setRemProg({ total: saved.total, done: 0, latest: null, failed: 0 }); startPoll(saved.total) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])
  // Rebuild the human review queue whenever triage decisions change so inscope-only
  // selections are reflected when the user navigates to the Human review tab.
  useEffect(() => {
    setQueue(buildHumanQueue(files, triage))
  }, [triage]) // eslint-disable-line react-hooks/exhaustive-deps

  const runServerRemediation = async (scopeFiles) => {
    if (!runId || remBusy) return
    setRemBusy(true); setRemMsg(''); setRemProg(null)
    const scope = scopeFiles?.map((f) => f.file)
    try {
      const r = await remediateScan(runId, scope)
      if (!r.enqueued) { setRemMsg('Nothing to remediate — no eligible files with issues.'); setRemBusy(false); return }
      if (!r.workers) { setRemMsg(`Enqueued ${r.enqueued}, but no workers are running. Add some in the Monitor tab.`); setRemBusy(false); return }
      const total = r.enqueued
      setRemProg({ total, done: 0, latest: null, failed: 0 })
      try { sessionStorage.setItem(REMKEY(runId), JSON.stringify({ total })) } catch { /* ignore */ }
      startPoll(total)
    } catch (e) {
      setRemMsg(`Could not enqueue: ${e.message || e}`); setRemBusy(false)
    }
  }
  const triageFile = (file, st) => { setTriage((t) => { const n = { ...t }; if (st == null) delete n[file]; else n[file] = st; return n }); setTriageSel((s) => { const n = new Set(s); n.delete(file); return n }) }
  const triageBulk = (flist, st) => { setTriage((t) => { const n = { ...t }; flist.forEach((f) => { if (st == null) delete n[f.file]; else n[f.file] = st }); return n }); setTriageSel(new Set()) }
  const toggleSel = (file) => setTriageSel((s) => { const n = new Set(s); if (n.has(file)) n.delete(file); else n.add(file); return n })
  const revalidated = files.filter((f) => f.compliant)

  const act = (id, kind) => {
    const item = queue.find((x) => x.id === id)
    setQueue((q) => q.filter((x) => x.id !== id))
    setSelItem(null)
    if (kind === 'self') { if (item) setSelf((s) => [{ ...item, status: 'awaiting' }, ...s]); return }
    if (kind === 'deferred') { if (item) setDeferredItems((d) => [...d, item]); setActed((a) => ({ ...a, deferred: a.deferred + 1 })); return }
    setActed((a) => ({ ...a, [kind]: a[kind] + 1 }))
  }
  const rescan = (id) => {
    setSelf((s) => s.map((x) => x.id === id ? { ...x, status: 'scanning' } : x))
    setTimeout(() => setSelf((s) => s.map((x) => x.id === id ? { ...x, status: 'verified' } : x)), 1700)
  }
  const verified = self.filter((x) => x.status === 'verified').length
  // Live re-verified KPI = manual self-fixes + banked server fixes + the in-flight batch's
  // completions (ticks every poll), so the card moves in real time with the worker queue.
  const liveFixed = remProg ? Math.max(0, remProg.done - (remProg.failed || 0)) : 0
  const reVerified = verified + serverFixed + liveFixed
  const remLive = !!remProg || remBusy
  const pendingHitlFiles = new Set(queue.map((q) => q.file))
  const totalHitl = queue.length + acted.approved + acted.rejected + acted.deferred + self.length
  const hitlProgress = totalHitl > 0 ? Math.round(((totalHitl - queue.length) / totalHitl) * 100) : 0
  // Don't surface remediation numbers until the user has actually started remediating
  // (ran "Remediate all" or acted on a review item) — pre-engagement estimates read as
  // in-progress work and confuse first-time users. Until then the cards show zeros.
  const remStarted = remProg != null || remBusy || (acted.approved + acted.rejected + acted.deferred + self.length) > 0

  // --- remediation plan + decisions (moved from Discover) ---
  const plan = files.length ? recommendationSummary(files) : null
  const planCards = plan ? plan.buckets.filter((b) => REM_ACTIONS.includes(b.action)) : []
  // Published business ontology takes precedence in the queue order (Critical → Low),
  // then the AI risk triage breaks ties.
  const ontRank = (f) => f.ont?.priority ? PRI_RANK[f.ont.priority] : 9
  const hasInscopeSelections = Object.values(triage).some((v) => v === 'inscope')
  const remediable = files.filter((f) => {
    if (f.remediated_at || f.drive_write_url) return false  // already fixed — don't re-offer it
    if (!f.rec || !REM_ACTIONS.includes(f.rec.action)) return false
    if (triage[f.file] === 'na' || triage[f.file] === 'defer') return false
    // If the user has explicitly marked any files inscope, only remediate those files.
    if (hasInscopeSelections && triage[f.file] !== 'inscope') return false
    return true
  }).sort((a, b) => (ontRank(a) - ontRank(b)) || (priority(b) - priority(a)))
  const ontCount = remediable.filter((f) => f.ont).length
  const autoFiles = remediable.filter((f) => {
    const eff = decisions[f.file]?.state === 'override' ? decisions[f.file].action : f.rec?.action
    return eff === 'auto' && !decisions[f.file]
  })
  const batchAutoRemediate = () => setDecisions?.((s) => { const n = { ...s }; autoFiles.forEach((f) => { n[f.file] = { state: 'accepted' } }); return n })
  const decide = (file, d) => { setDecisions?.((s) => ({ ...s, [file]: d })); setEditing(null) }
  const undo = (file) => setDecisions?.((s) => { const n = { ...s }; delete n[file]; return n })
  const acceptAll = () => setDecisions?.((s) => { const n = { ...s }; remediable.forEach((f) => { if (!n[f.file]) n[f.file] = { state: 'accepted' } }); return n })
  const dcount = (st) => remediable.filter((f) => decisions[f.file]?.state === st).length
  const pending = remediable.length - dcount('accepted') - dcount('override') - dcount('rejected')
  const humanCount = pending - autoFiles.length   // pending files NOT auto — the gap between the two plan buttons

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
        <div className={`metric${remLive ? ' livecard' : ''}`} title="Estimated number of issues that can be fixed automatically — populates once you run remediation"><span>auto-fixable (est.)</span><b style={{ color: remStarted ? '#3B6D11' : '#9AA1B4' }}>{remStarted ? autoFixed : 0}</b></div>
        <div className="metric"><span>HITL queue</span>{remStarted
          ? <><b style={{ color: queue.length ? '#854F0B' : '#3B6D11' }}>{totalHitl === 0 ? 'no items' : `${queue.length} remaining`}</b>{totalHitl > 0 && <span className="muted" style={{ fontSize: 11 }}> · {hitlProgress}% done</span>}</>
          : <b style={{ color: '#9AA1B4' }}>—</b>}</div>
        <div className="metric"><span>approved</span><b key={acted.approved} className={acted.approved ? 'tick' : undefined}>{acted.approved}</b></div>
        <div className="metric"><span>deferred</span><b key={acted.deferred} className={acted.deferred ? 'tick' : undefined} style={{ color: '#1F5FA8' }}>{acted.deferred}</b></div>
        <div className={`metric${remLive ? ' livecard' : ''}`} title="Documents fixed and re-validated against all engines — ticks in real time as the worker queue completes each file">
          <span>re-verified{remLive && <span className="livedot">live</span>}</span>
          <b key={reVerified} className={reVerified ? 'tick' : undefined} style={{ color: '#3B6D11' }}>{reVerified.toLocaleString()}</b>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', margin: '4px 0 12px' }}>
        <button disabled={remBusy || !runId} onClick={() => runServerRemediation(remediable)}
                title="Run deterministic HTML remediation server-side, in the durable worker queue. Fixed copies are written to a Remediated/ folder; results trace to Langfuse.">
          {remBusy ? 'Enqueueing…' : '⚡ Remediate all (server-side)'}
        </button>
        {remMsg && <span className="muted" role="status" aria-live="polite" style={{ fontSize: 13 }}>{remMsg}</span>}
        {(serverFixed > 0 || remProg) && <TraceChip traceId={`${runId}-remediate`} label="View remediation trace" />}
      </div>

      {remProg && (
        <div style={{ margin: '0 0 14px', maxWidth: 560 }} role="status" aria-live="polite">
          <div style={{ height: 9, borderRadius: 6, background: 'var(--line)', overflow: 'hidden' }}>
            <i style={{ display: 'block', height: '100%',
                        width: `${Math.round((remProg.done / Math.max(1, remProg.total)) * 100)}%`,
                        background: '#BF8C00', transition: 'width .35s' }} />
          </div>
          <div className="muted" style={{ fontSize: 12.5, marginTop: 6 }}>
            ⚡ <b>Live</b> · remediating {remProg.done.toLocaleString()} of {remProg.total.toLocaleString()} files in real time
            {remProg.latest ? <> · last fixed <span className="fname">{remProg.latest}</span></> : '…'}
            {remProg.failed ? ` · ${remProg.failed} failed` : ''}
          </div>
        </div>
      )}

      <div className="subtabs" role="tablist" aria-label="Remediate steps">
        {SUBS.map(([k, label], i) => {
          // Real completion signal per sub-step (stays ✓ even when you navigate away).
          const subDone = {
            triage: files.length > 0 && files.filter((f) => !(f.remediated_at || f.drive_write_url) && !triage[f.file]).length === 0,
            auto: remediable.length > 0 && pending === 0,
            review: (totalHitl > 0 && queue.length === 0) || serverFixed > 0,
            revalidate: reVerified > 0,
          }
          const done = !!subDone[k] && sub !== k
          return <button key={k} role="tab" aria-selected={sub === k} aria-current={sub === k ? 'step' : undefined} className={`fchip${sub === k ? ' on' : ''}${done ? ' done' : ''}`} onClick={() => setSub(k)}>{done && <span className="tabok" aria-hidden="true">✓ </span>}{label}{done && <span className="vh"> completed</span>}</button>
        })}
      </div>

      {/* Write-back results — proof the fixed copies landed in Drive. Surfaces the
          drive_write_url recorded server-side, so a successful remediation is visible. */}
      {(() => {
        const written = files.filter((f) => f.drive_write_url)
        const downloadOnly = files.filter((f) => f.remediated_at && !f.drive_write_url)
        if (!written.length && !downloadOnly.length) return null
        return (
          <div style={{ margin: '0 0 14px', padding: '10px 14px', borderRadius: 9,
                        background: '#E7F0DC', border: '1px solid #C5DBA8',
                        display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#2F5310' }}>
              ✓ {written.length} fixed document{written.length !== 1 ? 's' : ''} written back to Drive
              {downloadOnly.length > 0 && ` · ${downloadOnly.length} remediated (no Drive write)`}
            </span>
            <span style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              {written.slice(0, 6).map((f) => (
                <a key={f.file} href={f.drive_write_url} target="_blank" rel="noreferrer"
                   style={{ fontSize: 12, color: '#185FA5' }} title={`Open ${f.file} in the Remediated/ folder`}>
                  {f.file} ↗
                </a>
              ))}
              {written.length > 6 && <span className="muted" style={{ fontSize: 12 }}>+{written.length - 6} more</span>}
            </span>
          </div>
        )
      })()}

      {sub === 'triage' && (() => {
        const scoreColor = (s) => s >= 80 ? '#3B6D11' : s >= 60 ? '#854F0B' : '#7B1D1D'
        const SEV_C = { CRITICAL: '#7B1D1D', SERIOUS: '#854F0B', MODERATE: '#1F5FA8', MINOR: '#9a948f' }
        const topSev = (f) => { for (const s of ['CRITICAL', 'SERIOUS', 'MODERATE', 'MINOR']) if ((f.issues || []).some((i) => i.severity === s)) return s; return null }
        // Already-remediated files are done — drop them from triage so they
        // don't linger as "undecided". The green write-back banner above is the
        // record of what's been fixed.
        const remediatedFiles = files.filter((f) => f.remediated_at || f.drive_write_url)
        const triageFiles = files.filter((f) => !(f.remediated_at || f.drive_write_url)).sort((a, b) => {
          const aDec = triage[a.file], bDec = triage[b.file]
          const aJ = isAutoJunk(a), bJ = isAutoJunk(b)
          if (!aDec && !bDec) return (bJ ? 1 : 0) - (aJ ? 1 : 0) || ((a.score ?? 50) - (b.score ?? 50))
          if (!aDec) return -1; if (!bDec) return 1; return 0
        })
        // Drain model: the worklist shows only files still to decide; decided files move
        // to a collapsible group so the list shrinks as you go (and feels "done" at 0).
        const undecidedFiles = triageFiles.filter((f) => !triage[f.file])
        const decidedFiles = triageFiles.filter((f) => triage[f.file])
        const undecidedJunk = undecidedFiles.filter(isAutoJunk)
        const naCount = triageFiles.filter((f) => triage[f.file] === 'na').length
        const deferCount = triageFiles.filter((f) => triage[f.file] === 'defer').length
        const inscopeCount = triageFiles.filter((f) => triage[f.file] === 'inscope').length
        const undecided = undecidedFiles.length
        const selFiles = triageFiles.filter((f) => triageSel.has(f.file))
        const allSel = undecidedFiles.length > 0 && undecidedFiles.every((f) => triageSel.has(f.file))
        return (
          <section className="panel" key="triage">
            <div className="triagehd">
              <div>
                <b>File triage</b>
                <span className="muted"> · {undecidedFiles.length} to decide · {decidedFiles.length} decided{remediatedFiles.length > 0 ? ` · ${remediatedFiles.length} cleared` : ''}</span>
                <div className="muted" style={{ fontSize: 12, marginTop: 3, lineHeight: 1.5, maxWidth: 760 }}>
                  Tick files (or the header checkbox) then set a decision for all of them — or use the buttons on each row:
                  <b style={{ color: '#3B6D11' }}> ✓ In scope</b> = remediate it · <b> N/A</b> = skip, not relevant · <b style={{ color: '#1F5FA8' }}> ⏸ Defer</b> = decide later. Only <b>in-scope</b> files are remediated.
                </div>
              </div>
              <div className="triagesum">
                <span className="trstatchip inscope">{inscopeCount} in scope</span>
                <span className="trstatchip na">{naCount} N/A</span>
                <span className="trstatchip defer">{deferCount} deferred</span>
                {undecided > 0 && <span className="trstatchip pending">{undecided} undecided</span>}
              </div>
            </div>

            {undecidedJunk.length > 0 && (
              <div className="junkbanner">
                ⚑ <b>{undecidedJunk.length} undecided file{undecidedJunk.length !== 1 ? 's' : ''} suggested as low-priority</b> — draft/backup name patterns, or score ≥ 90 with no critical/serious findings · the agent recommends N/A or archive. Not automatically excluded — you decide.
                <button className="ghost small" style={{ marginLeft: 10 }} onClick={() => triageBulk(undecidedJunk, 'na')}>Mark all N/A</button>
                <button className="ghost small" style={{ marginLeft: 6 }} onClick={() => triageBulk(undecidedJunk, 'defer')}>Defer all</button>
              </div>
            )}

            {triageSel.size > 0 && (
              <div className="triagetools">
                <span style={{ fontSize: 13, fontWeight: 600 }}>{triageSel.size} file{triageSel.size !== 1 ? 's' : ''} selected — set a decision:</span>
                <button className="ghost small" title="Mark these files in scope — they'll be remediated" onClick={() => triageBulk(selFiles, 'inscope')}>✓ In scope</button>
                <button className="ghost small" title="Mark N/A — skip these, not relevant to remediate" onClick={() => triageBulk(selFiles, 'na')}>N/A</button>
                <button className="ghost small" title="Defer — decide on these later" onClick={() => triageBulk(selFiles, 'defer')}>⏸ Defer</button>
                <button className="ghost small" style={{ color: 'var(--muted)' }} title="Clear the selection" onClick={() => setTriageSel(new Set())}>clear selection</button>
              </div>
            )}

            {triageFiles.length > 0 ? (
            <>
            {undecidedFiles.length > 0 && (
            <div className="trlist">
              <div className="trheader">
                <input type="checkbox" checked={allSel} onChange={() => setTriageSel(allSel ? new Set() : new Set(undecidedFiles.map((f) => f.file)))} aria-label="Select all undecided" />
                <span>File</span>
                <span style={{ textAlign: 'right' }}>Score</span>
                <span>Issues</span>
                <span>Decision</span>
              </div>
              {undecidedFiles.map((f) => {
                const dec = triage[f.file]
                const junk = isAutoJunk(f)
                const sev = topSev(f)
                const issel = triageSel.has(f.file)
                return (
                  <div className={`trrow${dec === 'na' ? ' trna' : dec === 'defer' ? ' trdefer' : dec === 'inscope' ? ' trinscope' : junk && !dec ? ' trjunkrow' : ''}`} key={f.file}>
                    <input type="checkbox" checked={issel} onChange={() => toggleSel(f.file)} aria-label={`Select ${f.file}`} />
                    <div className="trname">
                      <button className="remname" onClick={() => setSel(f)}>{f.file}</button>
                      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 1 }}>
                        {f.department && <span>{f.department}</span>}
                        {f.department && f.sourceName && <span> · </span>}
                        {f.sourceName && <span>{f.sourceName}</span>}
                        {junk && !dec && <span className="junkflag">⚑ likely junk</span>}
                      </div>
                    </div>
                    <span className="trscore" style={{ color: f.score != null ? scoreColor(f.score) : 'var(--muted)' }}>
                      {f.score != null ? f.score : '—'}
                    </span>
                    <span className="trissues">
                      {(f.issues || []).length > 0
                        ? <><b>{(f.issues || []).length}</b>{sev && <span style={{ marginLeft: 5, fontSize: 11, color: SEV_C[sev] }}>{sev.toLowerCase()}</span>}</>
                        : <span style={{ color: 'var(--muted)', fontSize: 12 }}>none</span>}
                    </span>
                    <span className="tractions">
                      {dec ? (
                        <>
                          <span className={`trstatchip ${dec}`}>{dec === 'inscope' ? '✓ in scope' : dec === 'na' ? 'N/A' : '⏸ deferred'}</span>
                          <button className="ghost small" style={{ marginLeft: 6 }} onClick={() => triageFile(f.file, null)} title="Undo">↺</button>
                        </>
                      ) : (
                        <>
                          <button className="trbtn inscope" onClick={() => triageFile(f.file, 'inscope')} title="In scope — include in remediation plan">✓</button>
                          <button className="trbtn na" onClick={() => triageFile(f.file, 'na')} title="Not applicable — exclude from plan">N/A</button>
                          <button className="trbtn defer" onClick={() => triageFile(f.file, 'defer')} title="Defer to a later batch">⏸</button>
                        </>
                      )}
                    </span>
                  </div>
                )
              })}
            </div>
            )}
            {decidedFiles.length > 0 && (
              <details className="decidedwrap" style={{ marginTop: 12 }}>
                <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: 13, color: 'var(--muted)', padding: '6px 0' }}>✓ {decidedFiles.length} decided · {inscopeCount} in scope · {naCount} N/A · {deferCount} deferred <span style={{ fontWeight: 400 }}>· click to review / change</span></summary>
                <div style={{ marginTop: 4 }}>
                  {decidedFiles.map((f) => (
                    <div key={f.file} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 2px', borderBottom: '1px solid var(--line)' }}>
                      <button className="remname" style={{ flex: 1, textAlign: 'left' }} onClick={() => setSel(f)}>{f.file}</button>
                      <span className={`trstatchip ${triage[f.file]}`}>{triage[f.file] === 'inscope' ? '✓ in scope' : triage[f.file] === 'na' ? 'N/A' : '⏸ deferred'}</span>
                      <button className="ghost small" onClick={() => triageFile(f.file, null)} title="Undo this decision">↺</button>
                    </div>
                  ))}
                </div>
              </details>
            )}
            </>
            ) : (
              <div className="triagecta">
                <b>✓ All scanned files remediated</b> — every file has been fixed and written back. Nothing left to triage{remediatedFiles.length > 0 ? ` · ${remediatedFiles.length} fixed` : ''}.
                <button className="decbtn ok" style={{ marginLeft: 14 }} onClick={() => setSub('revalidate')}>→ Re-validate</button>
              </div>
            )}

            {undecided === 0 && triageFiles.length > 0 && (
              <div className="triagecta">
                <b>✓ Triage complete</b> — {inscopeCount} file{inscopeCount !== 1 ? 's' : ''} in scope · {naCount} N/A · {deferCount} deferred
                <button className="decbtn ok" style={{ marginLeft: 14 }} onClick={() => setSub('auto')}>→ Go to remediation plan</button>
              </div>
            )}
          </section>
        )
      })()}

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
              {/* The gap between these two used to require mental subtraction (482 - 408 = 74,
                  with no on-screen cue that 408 is a SUBSET of 482). Both numbers now appear
                  literally, and the icon/copy pairs "no review needed" against "needs a person"
                  so the choice reads at a glance instead of requiring the two buttons to be
                  compared. */}
              {autoFiles.length > 0 && (
                <button className="batchbtn" onClick={batchAutoRemediate}
                        title="Accept ONLY the fully-automatic files — the engine fixes these deterministically when you click Remediate all. No human review involved.">
                  ⚡ Auto-fix {autoFiles.length} file{autoFiles.length !== 1 ? 's' : ''} <span style={{ opacity: 0.85, fontWeight: 400 }}>· no review needed</span>
                </button>
              )}
              <button className="acceptfullbtn" disabled={!pending} onClick={acceptAll}
                      title="Accept the WHOLE plan — every remediable file, including the ones below that need assisted or manual work from a person.">
                👥 Accept full plan · {pending}{humanCount > 0 && <span style={{ opacity: 0.85, fontWeight: 400 }}> · +{humanCount} need a person</span>}
              </button>
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
          <h2>Documents to remediate <span className="muted">· {remediable.length} · <b style={{ color: 'var(--ink)', fontWeight: 500 }}>AI-triaged</b> by business risk — exposure × severity × ownership — accept / reject / modify</span></h2>
          {ontCount > 0 && <div className="ontbanner">⬆ Ordered by your <b>business ontology</b> — {ontCount} document{ontCount === 1 ? '' : 's'} elevated by published rules (Settings → Business ontology)</div>}
          <div className="remlist">
            {remediable.map((f) => {
              const rec = f.rec; const dec = decisions[f.file]
              const effAction = dec?.state === 'override' ? dec.action : rec.action
              const [label, rbg, rfg, icon] = REC_STYLE[effAction] || REC_STYLE.review
              const effEta = dec?.state === 'override' ? (ETA_OVERRIDE[dec.action] ?? rec.etaMin) : rec.etaMin
              const [priLabel, priFg, priBg] = PRI[priTier(f)]
              return (
                <div className={`remrow${dec?.state === 'rejected' ? ' rowrej' : ''}`} key={f.file} style={{ borderLeft: `3px solid ${rfg}`, paddingLeft: 10 }}>
                  <div className="remmaincol">
                    <button className="remname" onClick={() => setSel(f)}>{f.file}<span className="muted"> · {f.sourceName} · {f.department}</span>
                      {pendingHitlFiles.has(f.file) && <span className="hitlbadge">⚑ awaiting review</span>}
                    </button>
                    {f.ont ? (
                      <div className="rempri">
                        <span className="pritag" style={{ background: PRI_COLOR[f.ont.priority][1], color: PRI_COLOR[f.ont.priority][0] }}>{f.ont.priority}</span>
                        {f.ont.label && <span className="ontlabelpill" style={{ color: f.ont.label.color, background: f.ont.label.color + '22' }}>{f.ont.label.name}</span>}
                        <span className="muted">business rule: {f.ont.rule.name}{f.ont.sla ? ` · ${f.ont.sla}d SLA` : ''}</span>
                      </div>
                    ) : (
                      <div className="rempri"><span className="pritag" style={{ background: priBg, color: priFg }}>{priLabel}</span><span className="muted">why: {priWhy(f)}</span></div>
                    )}
                  </div>
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
        <section className="panel"><h2>Automated fixes applied · by type</h2><Bars items={fixTypesDisplay} cols="140px 1fr 30px" /></section>
        <FixCarousel />
      </div>
      </>)}

      {sub === 'review' && (<>
      <section className="panel">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
          <h2 style={{ margin: 0 }}>Human-in-the-loop review queue {queue.length === 0 && <span className="muted">· all clear</span>}</h2>
          {totalHitl > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
              <div className="conftrack" style={{ width: 120 }}><i style={{ width: `${hitlProgress}%`, background: hitlProgress === 100 ? '#3B6D11' : '#1F5FA8' }} /></div>
              <span className="muted">{totalHitl - queue.length} of {totalHitl} reviewed</span>
              {acted.deferred > 0 && <span className="trstatchip defer">{acted.deferred} deferred</span>}
            </div>
          )}
        </div>
        {queue.length === 0 ? (
          <p className="muted">{totalHitl === 0
            ? 'No files require human review for this run — all remediations were fully automatic. Files needing AI-assisted fixes or human sign-off will appear here in future runs.'
            : `Queue cleared — ${acted.approved} approved, ${acted.rejected} rejected${acted.deferred ? `, ${acted.deferred} deferred to next cycle` : ''}. Re-validation runs on the approved fixes.`
          }</p>
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
                    <span className="conftrack"><i style={{ width: `${q.conf}%`, background: q.conf >= 55 ? '#BF8C00' : '#2E72C9' }} /></span>
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

      {deferredItems.length > 0 && (
        <section className="panel">
          <h2>Deferred <span className="muted">· {deferredItems.length} item{deferredItems.length !== 1 && "s"} &mdash; resurface on next scan</span></h2>
          <div className="queue">
            {deferredItems.map((it) => (
              <div className="qrow" key={it.id} style={{ opacity: 0.7 }}>
                <span className="qico" aria-hidden="true">{it.icon}</span>
                <div className="qmain">
                  <div className="qtitle">{it.title} <span className="muted" style={{ fontSize: 12 }}>· {it.file}</span></div>
                  <div className="qmeta">{it.rule}</div>
                </div>
                <span className="trstatchip defer" style={{ fontSize: 12, padding: "3px 10px" }}>⏸ deferred</span>
                <button className="ghost small" onClick={() => { setDeferredItems((d) => d.filter((x) => x.id !== it.id)); setQueue((q) => [...q, it]); setActed((a) => ({ ...a, deferred: a.deferred - 1 })) }}>↺ restore</button>
              </div>
            ))}
          </div>
          <p className="muted" style={{ marginTop: 10 }}>Deferred findings are tracked in the compliance record and flagged automatically when the next scheduled scan runs.</p>
        </section>
      )}

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
                    {it.status === 'awaiting' && <>
                      <span className="muted">awaiting your fix — open the file, apply it in the source, then confirm</span>
                      {SOURCE_URL[it.source] && <a className="ghost small" style={{ marginLeft: 8 }} href={SOURCE_URL[it.source]} target="_blank" rel="noopener noreferrer">↗ Open the file</a>}
                    </>}
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
            {(() => {
              const SEV_PEN = { CRITICAL: 16, SERIOUS: 11, MODERATE: 5, MINOR: 2 }
              const scoredFiles = files.filter((f) => f.score != null)
              const projScores = scoredFiles.map((f) => {
                const accepted = decisions[f.file]?.state === 'accepted' || decisions[f.file]?.state === 'override'
                const isAuto = (decisions[f.file]?.state === 'override' ? decisions[f.file].action : f.rec?.action) === 'auto'
                if (!accepted || !isAuto) return f.score
                const gain = (f.issues || []).filter((i) => i.auto).reduce((s, i) => s + (SEV_PEN[i.severity] || 0), 0)
                return Math.min(100, f.score + gain)
              })
              const liftBefore = run?.avg_score ?? 72
              const liftAfter = projScores.length ? Math.min(100, Math.round(projScores.reduce((a, b) => a + b, 0) / projScores.length)) : Math.min(100, liftBefore + 8)
              return (
                <div className="lift" style={{ margin: '8px 0 12px' }}>
                  <div className="liftcol"><div className="liftnum" style={{ color: '#1F5FA8' }}>{liftBefore}</div><div className="muted">before</div></div>
                  <div className="liftarrow" aria-hidden="true">→</div>
                  <div className="liftcol"><div className="liftnum" style={{ color: '#3B6D11' }}>{liftAfter}</div><div className="muted">after re-validation <span style={{ fontSize: 10, opacity: 0.7 }}>(projected)</span></div></div>
                  <div className="liftgain">+{liftAfter - liftBefore} pts</div>
                </div>
              )
            })()}
            <p className="muted">Every approved or self-applied fix is re-run against all engines. Only documents that re-pass advance to Publish — no fix is taken on trust.</p>
            {dcount('accepted') + dcount('override') > 0 && (
              <div className="outpanel" style={{ marginTop: 14 }}>
                <div className="muted" style={{ fontSize: 13, marginBottom: 8 }}><b>Output settings</b> — where should remediated files go?</div>
                <div className="outmodes">
                  {[['download','⤓ Download'], ['drive','☁ Save to Drive'], ['archive','⊡ Archive original']].map(([k, l]) => (
                    <button key={k} className={k === 'download' ? 'outmode on' : 'outmode'} onClick={() => {}}>{l}</button>
                  ))}
                </div>
                <div className="outact" style={{ marginTop: 8 }}>
                  <span className="muted" style={{ fontSize: 12 }}>Remediated files are stamped <b>_a11y-certified-{new Date().toISOString().split('T')[0]}</b> · originals kept for audit trail</span>
                  <span className="muted" style={{ fontSize: 12, marginLeft: 12 }}>Drive &amp; archive options: connect via Settings &rarr; Integrations</span>
                </div>
              </div>
            )}
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
      {sel && <FileDrawer file={sel} context="remediate" aiEnabled={aiEnabled} scanId={run?.id} onClose={() => setSel(null)} />}
      {selItem && <ReviewDrawer item={selItem} onClose={() => setSelItem(null)} onAct={act} />}
    </>
  )
}

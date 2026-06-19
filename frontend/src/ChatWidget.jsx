import { useState, useRef, useEffect } from 'react'
import { critLabel } from './FileDrawer.jsx'
import { statusSegments, severityItems } from './charts.jsx'
import ChatChart from './ChatChart.jsx'

const PLUM = '#7a5c8e'

// Chart-aware router: detects the dimension being asked about, computes it from the
// real scan, and returns { text, chart } so the answer can draw a bar/line/donut/heatmap.
// Returns null when nothing matches (caller then tries the LLM / synthetic fallback).
function chartAnswer(q, files, run, trend, trendDates) {
  if (!files.length || !run) return null
  const t = (q || '').toLowerCase()
  const flagged = files.filter((f) => (f.issues || []).length)
  const grpBar = (keyFn, color = PLUM, top = 8) => Object.entries(files.reduce((m, f) => { const k = keyFn(f); if (k != null) m[k] = (m[k] || 0) + 1; return m }, {}))
    .sort((a, b) => b[1] - a[1]).slice(0, top).map(([label, value]) => ({ label, value, color }))
  const findingsByDept = Object.entries(flagged.reduce((m, f) => { m[f.department] = (m[f.department] || 0) + f.issues.length; return m }, {})).sort((a, b) => b[1] - a[1])

  // trend over time → line
  if (/trend|over time|over the|history|progress|improv|trajectory|month/.test(t) && trend && trend.length > 1)
    return { text: `Compliance has climbed from ${trend[0]} to ${trend[trend.length - 1]} over ${trend.length} scans — a steady upward trend.`, chart: { type: 'line', points: trend, labels: trendDates } }

  // department × severity → heatmap
  if (/heat ?map|matrix|cross|department.*sever|sever.*depart|by department and|grid/.test(t)) {
    const sevs = ['CRITICAL', 'SERIOUS', 'MODERATE', 'MINOR']
    const dm = {}; files.forEach((f) => (f.issues || []).forEach((i) => { (dm[f.department] = dm[f.department] || {})[i.severity] = (dm[f.department]?.[i.severity] || 0) + 1 }))
    const topD = Object.entries(dm).map(([d, sv]) => [d, sevs.reduce((a, s) => a + (sv[s] || 0), 0)]).sort((a, b) => b[1] - a[1]).slice(0, 6).map((x) => x[0])
    if (!topD.length) return null
    return { text: 'Findings by department × severity (your highest-finding departments):', chart: { type: 'heatmap', rows: topD, cols: ['crit', 'serious', 'mod', 'minor'], matrix: topD.map((d) => sevs.map((s) => dm[d][s] || 0)) } }
  }

  // by department → bar (findings)
  if (/department|dept|team|unit|division/.test(t)) {
    if (!findingsByDept.length) return null
    return { text: `${findingsByDept[0][0]} has the most findings (${findingsByDept[0][1]}). Findings by department:`, chart: { type: 'bar', data: findingsByDept.slice(0, 8).map(([label, value]) => ({ label, value, color: PLUM })) } }
  }
  // by source → bar
  if (/source|drive|sharepoint|box|confluence|where.*from|repositor/.test(t))
    return { text: 'Documents by source:', chart: { type: 'bar', data: grpBar((f) => f.sourceName) } }
  // by type / format → bar
  if (/type|format|file kind|pdf|docx|pptx|xlsx/.test(t))
    return { text: 'Documents by type:', chart: { type: 'bar', data: grpBar((f) => (f.type || '').toUpperCase()) } }
  // severity → bar
  if (/sever|critical|serious|moderate|minor/.test(t)) {
    const data = severityItems(files); if (!data.length) return null
    return { text: 'Open findings by severity:', chart: { type: 'bar', data } }
  }
  // status / compliance breakdown → donut
  if (/status|breakdown|certifiable|pie|donut|distribution|how many.*(certif|pass|fail)/.test(t))
    return { text: 'Compliance status across the estate:', chart: { type: 'donut', data: statusSegments(run), caption: 'docs' } }
  // top WCAG → bar
  if (/wcag|violation|criteri|guideline|rule|fail/.test(t)) {
    const wm = {}; files.forEach((f) => (f.issues || []).forEach((i) => { wm[i.wcag] = (wm[i.wcag] || 0) + 1 }))
    const data = Object.entries(wm).sort((a, b) => b[1] - a[1]).slice(0, 7).map(([w, n]) => ({ label: critLabel(w).replace(/^WCAG\s*/, ''), value: n, color: n >= 8 ? '#E24B4A' : '#F5B400' }))
    if (!data.length) return null
    return { text: 'Top WCAG violations across your documents:', chart: { type: 'bar', data, gridCols: '150px 1fr 26px' } }
  }
  // generic ask to visualise → default to findings by department
  if (/chart|graph|plot|visuali|diagram|^show|bar|map of/.test(t) && findingsByDept.length)
    return { text: "Here's your findings by department:", chart: { type: 'bar', data: findingsByDept.slice(0, 8).map(([label, value]) => ({ label, value, color: PLUM })) } }
  return null
}

// Optional real-LLM endpoint for free-form questions. Defaults to the bundled Netlify
// function when deployed on *.netlify.app; set VITE_ASK_ENDPOINT for other hosts. When
// absent (or it returns nothing), a synthetic, data-grounded fallback is used instead.
const LLM_ENDPOINT = import.meta.env.VITE_ASK_ENDPOINT || (typeof location !== 'undefined' && /netlify\.app$/.test(location.hostname) ? '/.netlify/functions/ask' : null)
const delay = (ms) => new Promise((r) => setTimeout(r, ms))

// Rule-based answers for the common questions — returns null when nothing matches.
function matchAnswer(q, files, run) {
  const t = (q || '').toLowerCase()
  if (!files.length || !run) return 'Run a scan first and I can answer questions about your documents.'
  const flagged = files.filter((f) => (f.issues || []).length)
  const totalIssues = files.reduce((a, f) => a + (f.issues?.length || 0), 0)
  const tagCount = (tag) => files.filter((f) => (f.tags || []).includes(tag)).length
  const grp = (key) => { const m = {}; files.forEach((f) => { const k = typeof key === 'function' ? key(f) : f[key]; if (k != null) m[k] = (m[k] || 0) + 1 }); return Object.entries(m).sort((a, b) => b[1] - a[1]) }
  const deptIssues = {}; flagged.forEach((f) => { deptIssues[f.department] = (deptIssues[f.department] || 0) + f.issues.length })
  const topDept = Object.entries(deptIssues).sort((a, b) => b[1] - a[1])[0]
  const wm = {}; files.forEach((f) => (f.issues || []).forEach((i) => { wm[i.wcag] = (wm[i.wcag] || 0) + 1 }))
  const topWcag = Object.entries(wm).sort((a, b) => b[1] - a[1])[0]
  const pct = (n) => Math.round((n / run.files) * 100)

  if (/score|complian|overall|how.*(doing|look)/.test(t)) return `Estate compliance score is ${run.avg_score}/100. ${run.certifiable} of ${run.files} documents are certifiable (${pct(run.certifiable)}%); ${flagged.length} have open findings.`
  if (/department|dept|team|unit/.test(t)) return topDept ? `${topDept[0]} has the most findings — ${topDept[1]} across its documents. Your estate spans ${new Set(files.map((f) => f.department)).size} departments.` : 'No department findings.'
  if (/source|drive|sharepoint|box|confluence|where.*from/.test(t)) { const s = grp('sourceName'); return `Documents come from ${s.length} sources. ${s[0][0]} has the most (${s[0][1]} documents).` }
  if (/wcag|violation|criteri|fail|finding|issue|problem/.test(t)) return `${totalIssues} findings across ${flagged.length} documents. Most common: WCAG ${critLabel(topWcag[0])} — ${topWcag[1]} documents.`
  if (/pii|sensitive|confidential|legal|hold/.test(t)) return `${tagCount('PII')} documents are tagged PII and ${tagCount('legal-hold')} are under legal hold. Those carry the highest risk if exposed.`
  if (/public|high.?traffic|facing|exposure|risk/.test(t)) return `${tagCount('public-facing')} documents are public-facing and ${tagCount('high-traffic')} are high-traffic — the top legal-exposure set under ADA/EAA.`
  if (/certif|pass|compliant|clean|ready/.test(t)) return `${run.certifiable} documents are certifiable. ${run.uncertain} are uncertain (a rule couldn't be evaluated) and ${run.error} couldn't be analysed.`
  if (/remediat|fix|auto|resolve/.test(t)) return `${flagged.length} documents need remediation. Common findings (alt text, headings, language) auto-fix; low-confidence fixes escalate to human review.`
  if (/type|format|pdf|docx|pptx/.test(t)) { const ty = grp((f) => (f.type || '').toUpperCase()); return `By type: ${ty.slice(0, 4).map(([k, n]) => `${k} ${n}`).join(', ')}.` }
  if (/^(hi|hey|hello|help|what can|who)/.test(t)) return `Ask me about your ${run.files}-document scan — score, top WCAG violations, departments, sources, PII/legal exposure, or remediation.`
  return null
}

function dataSummary(files, run) {
  const flagged = files.filter((f) => (f.issues || []).length)
  const wm = {}; files.forEach((f) => (f.issues || []).forEach((i) => { wm[i.wcag] = (wm[i.wcag] || 0) + 1 }))
  const di = {}; flagged.forEach((f) => { di[f.department] = (di[f.department] || 0) + f.issues.length })
  const tag = (t) => files.filter((f) => (f.tags || []).includes(t)).length
  return {
    documents: run.files, certifiable: run.certifiable, uncertain: run.uncertain, unanalysable: run.error,
    avg_score: run.avg_score, flagged: flagged.length,
    top_wcag: Object.entries(wm).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([w, n]) => ({ criterion: critLabel(w), documents: n })),
    findings_by_department: Object.entries(di).sort((a, b) => b[1] - a[1]).slice(0, 6),
    pii: tag('PII'), legal_hold: tag('legal-hold'), public_facing: tag('public-facing'),
  }
}

function synthAnswer(files, run) {
  const flagged = files.filter((f) => (f.issues || []).length).length
  return `Across your ${run.files}-document scan (average ${run.avg_score}/100, ${flagged} with open findings), I don't have an exact metric for that. Try asking me to chart something — "findings by department", "compliance trend over time", "severity heatmap" — or about your score, top WCAG violations, sources, or PII/legal exposure.`
}

// Returns { text, ai } so the UI can show whether Claude answered (ai:true) or the
// data-grounded synthetic fallback did (ai:false).
async function askCustom(q, files, run) {
  if (LLM_ENDPOINT) {
    try {
      const ctrl = new AbortController(); const tm = setTimeout(() => ctrl.abort(), 12000)
      const res = await fetch(LLM_ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q, context: dataSummary(files, run) }), signal: ctrl.signal })
      clearTimeout(tm)
      if (res.ok) { const d = await res.json(); if (d && d.answer) return { text: d.answer, ai: true } }
    } catch { /* fall through to synthetic */ }
  }
  return { text: synthAnswer(files, run), ai: false }
}

const SUGGEST = ["What's my compliance score?", 'Findings by department', 'Compliance trend over time', 'Severity heatmap', 'Top WCAG violations']

export default function ChatWidget({ files = [], run, trend = [], trendDates = [] }) {
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [msgs, setMsgs] = useState([{ role: 'bot', text: 'Hi — ask me anything about your scanned documents.' }])
  const [input, setInput] = useState('')
  const [thinking, setThinking] = useState(false)
  const endRef = useRef(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, open, thinking])
  useEffect(() => {
    if (!open) return
    const k = (e) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [open])

  const send = async (text) => {
    const q = (text ?? input).trim()
    if (!q || thinking) return
    setInput('')
    setMsgs((m) => [...m, { role: 'user', text: q }])
    setThinking(true)
    const charted = chartAnswer(q, files, run, trend, trendDates)
    const matched = charted ? null : matchAnswer(q, files, run)
    let reply
    if (charted) { await delay(800 + Math.floor(Math.random() * 700)); reply = charted }
    else if (matched) { await delay(750 + Math.floor(Math.random() * 600)); reply = { text: matched } }
    else { await delay(450); reply = await askCustom(q, files, run) }
    setMsgs((m) => [...m, { role: 'bot', ...reply }])
    setThinking(false)
  }

  return (
    <>
      <button className="chatfab" aria-label={open ? 'Close assistant' : 'Ask about your data'} onClick={() => setOpen((o) => !o)}>
        {open ? '✕' : (
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.4 8.5 8.5 0 0 1-3.9-.9L3 21l1.9-5.1A8.38 8.38 0 0 1 4 11.5 8.5 8.5 0 0 1 12.5 3 8.38 8.38 0 0 1 21 11.5z" /></svg>
        )}
      </button>
      {open && (
        <aside className={expanded ? 'chatpanel expanded' : 'chatpanel'} role="dialog" aria-label="Compliance assistant">
          <div className="chathead">
            <div><b>Compliance assistant</b><span className="muted"> · about your scan</span>{LLM_ENDPOINT && <span className="chatlive" title="Live AI answers are enabled for free-form questions">✦ live AI</span>}</div>
            <button className="chatexpand" aria-label={expanded ? 'Collapse chat' : 'Expand chat'} title={expanded ? 'Collapse' : 'Expand'} onClick={() => setExpanded((e) => !e)}>
              {expanded
                ? <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 9H4M9 9V4M9 9 4 4M15 9h5M15 9V4m0 5 5-5M9 15H4m5 0v5m0-5-5 5m11-5h5m-5 0v5m0-5 5 5" /></svg>
                : <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" /></svg>}
            </button>
          </div>
          <div className="chatmsgs" role="log" aria-live="polite">
            {msgs.map((m, i) => <div key={i} className={`chatmsg ${m.role}${m.chart ? ' haschart' : ''}`}>{m.text}{m.chart && <ChatChart chart={m.chart} />}{m.role === 'bot' && m.ai !== undefined && <span className={`aibadge ${m.ai ? 'on' : 'off'}`} title={m.ai ? 'Answered by Claude (live AI)' : 'Answered offline from your scan data — no live AI'}>{m.ai ? '✦ Claude' : '◴ offline'}</span>}</div>)}
            {thinking && <div className="chatmsg bot thinking"><span className="typing"><i /><i /><i /></span><span className="muted" style={{ fontSize: 12 }}>analyzing your scan…</span></div>}
            <div ref={endRef} />
          </div>
          <div className="chatchips">
            {SUGGEST.map((s) => <button key={s} className="chatchip" disabled={thinking} onClick={() => send(s)}>{s}</button>)}
          </div>
          <form className="chatinput" onSubmit={(e) => { e.preventDefault(); send() }}>
            <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about your documents…" aria-label="Ask a question" />
            <button type="submit" aria-label="Send" disabled={thinking}>→</button>
          </form>
        </aside>
      )}
    </>
  )
}

import { useState, useRef, useEffect } from 'react'
import { critLabel } from './FileDrawer.jsx'

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
  return `Across your ${run.files}-document scan (average ${run.avg_score}/100, ${flagged} with open findings), I don't have an exact metric for that. I can pull precise numbers on your compliance score, top WCAG violations, departments, sources, PII/legal exposure, document types, or remediation — try one of those.`
}

async function askCustom(q, files, run) {
  if (LLM_ENDPOINT) {
    try {
      const ctrl = new AbortController(); const tm = setTimeout(() => ctrl.abort(), 12000)
      const res = await fetch(LLM_ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q, context: dataSummary(files, run) }), signal: ctrl.signal })
      clearTimeout(tm)
      if (res.ok) { const d = await res.json(); if (d && d.answer) return d.answer }
    } catch { /* fall through to synthetic */ }
  }
  return synthAnswer(files, run)
}

const SUGGEST = ["What's my compliance score?", 'Which department has the most issues?', 'Top WCAG violations?', 'How many PII documents?']

export default function ChatWidget({ files = [], run }) {
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [msgs, setMsgs] = useState([{ role: 'bot', text: 'Hi — ask me anything about your scanned documents.' }])
  const [input, setInput] = useState('')
  const [thinking, setThinking] = useState(false)
  const endRef = useRef(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, open, thinking])

  const send = async (text) => {
    const q = (text ?? input).trim()
    if (!q || thinking) return
    setInput('')
    setMsgs((m) => [...m, { role: 'user', text: q }])
    setThinking(true)
    const matched = matchAnswer(q, files, run)
    let reply
    if (matched) { await delay(750 + Math.floor(Math.random() * 600)); reply = matched }
    else { await delay(450); reply = await askCustom(q, files, run) }
    setMsgs((m) => [...m, { role: 'bot', text: reply }])
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
            <div><b>Compliance assistant</b><span className="muted"> · about your scan</span></div>
            <button className="chatexpand" aria-label={expanded ? 'Collapse chat' : 'Expand chat'} title={expanded ? 'Collapse' : 'Expand'} onClick={() => setExpanded((e) => !e)}>
              {expanded
                ? <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 9H4M9 9V4M9 9 4 4M15 9h5M15 9V4m0 5 5-5M9 15H4m5 0v5m0-5-5 5m11-5h5m-5 0v5m0-5 5 5" /></svg>
                : <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" /></svg>}
            </button>
          </div>
          <div className="chatmsgs">
            {msgs.map((m, i) => <div key={i} className={`chatmsg ${m.role}`}>{m.text}</div>)}
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

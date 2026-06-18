import { useState, useRef, useEffect } from 'react'
import { critLabel } from './FileDrawer.jsx'

// "Ask Aria" — a floating assistant. Answers are computed from the live scan data,
// so questions about the estate get real numbers (no backend / LLM in the demo).
function answer(q, files, run) {
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
  if (/^(hi|hey|hello|help|what can|who are)/.test(t)) return `I'm Aria. Ask me about your ${run.files}-document scan — score, top WCAG violations, departments, sources, PII/legal exposure, or remediation.`
  return `I can answer from your ${run.files}-document scan — compliance score, top WCAG violations, departments, sources, PII/legal exposure, document types, and remediation. Try a suggestion below.`
}

const SUGGEST = ["What's my compliance score?", 'Which department has the most issues?', 'Top WCAG violations?', 'How many PII documents?']

export default function ChatWidget({ files = [], run }) {
  const [open, setOpen] = useState(false)
  const [msgs, setMsgs] = useState([{ role: 'bot', text: "Hi, I'm Aria. Ask me anything about your scanned documents." }])
  const [input, setInput] = useState('')
  const endRef = useRef(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, open])

  const send = (text) => {
    const q = (text ?? input).trim()
    if (!q) return
    setMsgs((m) => [...m, { role: 'user', text: q }, { role: 'bot', text: answer(q, files, run) }])
    setInput('')
  }

  return (
    <>
      <button className="chatfab" aria-label={open ? 'Close assistant' : 'Ask Aria about your data'} onClick={() => setOpen((o) => !o)}>
        {open ? '✕' : (
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.4 8.5 8.5 0 0 1-3.9-.9L3 21l1.9-5.1A8.38 8.38 0 0 1 4 11.5 8.5 8.5 0 0 1 12.5 3 8.38 8.38 0 0 1 21 11.5z" /></svg>
        )}
      </button>
      {open && (
        <aside className="chatpanel" role="dialog" aria-label="Ask Aria">
          <div className="chathead"><b>Ask Aria</b><span className="muted"> · about your scan</span></div>
          <div className="chatmsgs">
            {msgs.map((m, i) => <div key={i} className={`chatmsg ${m.role}`}>{m.text}</div>)}
            <div ref={endRef} />
          </div>
          <div className="chatchips">
            {SUGGEST.map((s) => <button key={s} className="chatchip" onClick={() => send(s)}>{s}</button>)}
          </div>
          <form className="chatinput" onSubmit={(e) => { e.preventDefault(); send() }}>
            <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about your documents…" aria-label="Ask a question" />
            <button type="submit" aria-label="Send">→</button>
          </form>
        </aside>
      )}
    </>
  )
}

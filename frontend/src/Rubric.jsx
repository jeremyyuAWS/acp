import { useEffect, useState } from 'react'
import { getRules, getRubric, updateRubric } from './api'

const SEV = {
  CRITICAL: ['#FCEBEB', '#A32D2D'], SERIOUS: ['#FAEEDA', '#854F0B'],
  MODERATE: ['#E6F1FB', '#185FA5'], MINOR: ['#F1EFE8', '#5F5E5A'],
}
const SEVRANK = { CRITICAL: 0, SERIOUS: 1, MODERATE: 2, MINOR: 3 }
const FMT = { docx: 'Word', pptx: 'PowerPoint', xlsx: 'Excel', pdf: 'PDF' }
const wcag = (c) => (c?.startsWith('SC_') ? c.slice(3).replace(/_/g, '.') : c)

export default function Rubric({ onSaved }) {
  const [rules, setRules] = useState(null)
  const [threshold, setThreshold] = useState(90)
  const [saving, setSaving] = useState(false)
  const [savedHash, setSavedHash] = useState(null)
  const [filter, setFilter] = useState('all')
  const [q, setQ] = useState('')

  useEffect(() => {
    getRules().then(setRules).catch(() => {})
    getRubric().then((r) => setThreshold(r.threshold)).catch(() => {})
  }, [])

  const dirty = () => setSavedHash(null)
  const toggle = (fmt, id) => { dirty(); setRules((r) => ({ ...r, [fmt]: r[fmt].map((x) => (x.id === id ? { ...x, enabled: !x.enabled } : x)) })) }
  const bulk = (fmt, on) => { dirty(); setRules((r) => ({ ...r, [fmt]: r[fmt].map((x) => ({ ...x, enabled: on })) })) }

  const save = async () => {
    setSaving(true)
    const disabled = Object.values(rules).flat().filter((r) => !r.enabled).map((r) => r.id)
    try {
      const res = await updateRubric({ disabled_rules: disabled, compliant_threshold: Number(threshold) })
      setSavedHash(res.hash); onSaved?.(res.hash)
    } finally { setSaving(false) }
  }

  if (!rules) return <p className="muted">Loading rules…</p>

  const all = Object.values(rules).flat()
  const total = all.length
  const on = all.filter((r) => r.enabled).length
  const sevCount = (s) => all.filter((r) => r.enabled && r.severity === s).length
  const totalFindings = all.reduce((a, r) => a + (r.findings || 0), 0)

  const match = (r) => {
    if (q && !`${r.title} ${r.id}`.toLowerCase().includes(q.toLowerCase())) return false
    if (filter === 'findings' && !(r.findings > 0)) return false
    if (filter === 'high' && !(r.severity === 'CRITICAL' || r.severity === 'SERIOUS')) return false
    return true
  }
  const sortRules = (arr) => [...arr].sort((a, b) => (b.findings || 0) - (a.findings || 0) || SEVRANK[a.severity] - SEVRANK[b.severity])

  return (
    <section className="panel">
      <div className="rubrichdr">
        <div>
          <h2 style={{ margin: 0 }}>Rule set</h2>
          <div className="muted" style={{ marginTop: 3 }}>{on} of {total} rules enabled · {totalFindings} findings in last scan</div>
        </div>
        <div className="rubricsave">
          <label>Compliant ≥ <input type="number" min="0" max="100" value={threshold} onChange={(e) => { setThreshold(e.target.value); dirty() }} /></label>
          <button disabled={saving} onClick={save}>{saving ? 'saving…' : 'Save rubric'}</button>
          {savedHash && <span className="muted">saved · {savedHash.slice(0, 8)}</span>}
        </div>
      </div>

      <div className="rubrictools">
        <div className="sevdist">
          {['CRITICAL', 'SERIOUS', 'MODERATE', 'MINOR'].map((s) => (
            <span key={s} className="sevpill" style={{ background: SEV[s][0], color: SEV[s][1] }}>{sevCount(s)} {s.toLowerCase()}</span>
          ))}
        </div>
        <div className="rubricfilters">
          <input className="rsearch" type="search" placeholder="search rules…" aria-label="Search rules" value={q} onChange={(e) => setQ(e.target.value)} />
          {[['all', 'All'], ['findings', 'With findings'], ['high', 'Critical & serious']].map(([k, l]) => (
            <button key={k} className={filter === k ? 'fchip on' : 'fchip'} onClick={() => setFilter(k)}>{l}</button>
          ))}
        </div>
      </div>

      {Object.entries(rules).map(([fmt, items]) => {
        const shown = sortRules(items.filter(match))
        if (!shown.length) return null
        const fon = items.filter((r) => r.enabled).length
        return (
          <div className="rulecard" key={fmt}>
            <div className="rulecardhdr">
              <div className="rulefmtname">{FMT[fmt] ?? fmt} <span className="muted">· {fon}/{items.length} enabled</span></div>
              <div className="bulk">
                <button className="linkbtn" onClick={() => bulk(fmt, true)}>enable all</button>
                <span className="muted">·</span>
                <button className="linkbtn" onClick={() => bulk(fmt, false)}>disable all</button>
              </div>
            </div>
            {shown.map((r) => {
              const [bg, fg] = SEV[r.severity] ?? SEV.MINOR
              return (
                <div className={r.enabled ? 'rulerow' : 'rulerow off'} key={r.id}>
                  <label className="switch"><input type="checkbox" checked={r.enabled} onChange={() => toggle(fmt, r.id)} aria-label={`${r.enabled ? 'Disable' : 'Enable'} rule: ${r.title}`} /><span className="slider" /></label>
                  <span className="ruletitle">{r.title}</span>
                  <span className="rulewcag"><span className="lvl">{r.level}</span> {wcag(r.wcag)}</span>
                  <span className="badge" style={{ background: bg, color: fg }}>{r.severity.toLowerCase()}</span>
                  <span className="ruleimpact">{r.findings > 0 ? <span className="impact">{r.findings} found</span> : <span className="muted">—</span>}</span>
                </div>
              )
            })}
          </div>
        )
      })}
    </section>
  )
}

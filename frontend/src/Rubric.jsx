import { useEffect, useState } from 'react'
import { getRules, getRubric, updateRubric } from './api'

const SEV = {
  CRITICAL: ['#FCEBEB', '#A32D2D'], SERIOUS: ['#FAEEDA', '#854F0B'],
  MODERATE: ['#E6F1FB', '#185FA5'], MINOR: ['#F1EFE8', '#5F5E5A'],
}
const FMT = { docx: 'Word', pptx: 'PowerPoint', xlsx: 'Excel', pdf: 'PDF' }
const wcag = (c) => (c?.startsWith('SC_') ? c.slice(3).replace(/_/g, '.') : c)

export default function Rubric({ onSaved }) {
  const [rules, setRules] = useState(null)
  const [threshold, setThreshold] = useState(90)
  const [saving, setSaving] = useState(false)
  const [savedHash, setSavedHash] = useState(null)

  useEffect(() => {
    getRules().then(setRules).catch(() => {})
    getRubric().then((r) => setThreshold(r.threshold)).catch(() => {})
  }, [])

  const toggle = (fmt, id) => {
    setSavedHash(null)
    setRules((r) => ({ ...r, [fmt]: r[fmt].map((x) => (x.id === id ? { ...x, enabled: !x.enabled } : x)) }))
  }

  const save = async () => {
    setSaving(true)
    const disabled = Object.values(rules).flat().filter((r) => !r.enabled).map((r) => r.id)
    try {
      const res = await updateRubric({ disabled_rules: disabled, compliant_threshold: Number(threshold) })
      setSavedHash(res.hash)
      onSaved?.(res.hash)
    } finally { setSaving(false) }
  }

  if (!rules) return <p className="muted">Loading rules…</p>

  const total = Object.values(rules).flat().length
  const on = Object.values(rules).flat().filter((r) => r.enabled).length

  return (
    <section className="panel">
      <div className="rubrichdr">
        <h2>Rule set · {on} of {total} enabled</h2>
        <div className="rubricsave">
          <label>Compliant ≥ <input type="number" min="0" max="100" value={threshold}
            onChange={(e) => { setThreshold(e.target.value); setSavedHash(null) }} /></label>
          <button disabled={saving} onClick={save}>{saving ? 'saving…' : 'Save rubric'}</button>
          {savedHash && <span className="muted">saved · rubric {savedHash.slice(0, 8)}</span>}
        </div>
      </div>
      <p className="muted" style={{ marginTop: -4, marginBottom: 14 }}>Disable a rule, save, then re-scan — the score updates and that rule stops counting.</p>

      {Object.entries(rules).map(([fmt, items]) => (
        <div className="rulegroup" key={fmt}>
          <div className="rulefmt">{FMT[fmt] ?? fmt}</div>
          {items.map((r) => {
            const [bg, fg] = SEV[r.severity] ?? SEV.MINOR
            return (
              <div className={r.enabled ? 'rulerow' : 'rulerow off'} key={r.id}>
                <label className="switch">
                  <input type="checkbox" checked={r.enabled} onChange={() => toggle(fmt, r.id)} />
                  <span className="slider" />
                </label>
                <span className="ruletitle">{r.title}</span>
                <span className="rulewcag">WCAG {wcag(r.wcag)}</span>
                <span className="badge" style={{ background: bg, color: fg }}>{r.severity.toLowerCase()}</span>
              </div>
            )
          })}
        </div>
      ))}
    </section>
  )
}

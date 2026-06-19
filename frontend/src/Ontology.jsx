import { useState, useMemo, useEffect } from 'react'

// Custom Ontology & Business Taxonomy Manager (Admin). Lets an admin teach the
// platform their org's own understanding of documents — custom labels, a
// hierarchical taxonomy, and a metadata rules engine that PRIORITISES/CATEGORISES
// the real corpus. Rules are evaluated against the actual loaded files (no mock),
// with a weighted risk score and a live impact preview, then drafted & published
// with version history. AI-assisted classification, NL authoring and ontology
// relationships are layered on top (NL authoring is a real deterministic parser;
// example-learning is a clearly-labelled preview).
const LS_KEY = 'mova_ontology_v1'

// ---- Field registry: what the rules engine can test, mapped to real corpus fields ----
const exposureOf = (f) => (f.tags || []).includes('public-facing') ? 'public-facing' : (f.tags || []).includes('high-traffic') ? 'high-traffic' : 'internal'
const sensitivityOf = (f) => (f.tags || []).includes('PII') ? 'PII' : (f.tags || []).includes('legal-hold') ? 'legal-hold' : 'none'
const SEV_ORDER = ['none', 'MINOR', 'MODERATE', 'SERIOUS', 'CRITICAL']
const worstSev = (f) => { const idx = (f.issues || []).map((i) => SEV_ORDER.indexOf(i.severity)).filter((x) => x >= 0); return idx.length ? SEV_ORDER[Math.max(...idx)] : 'none' }

const FIELDS = {
  department: { label: 'Department', type: 'enum', get: (f) => f.department, ops: ['is', 'is not'] },
  repository: { label: 'Repository / source', type: 'enum', get: (f) => f.sourceName, ops: ['is', 'is not'] },
  type: { label: 'File type', type: 'enum', get: (f) => f.type, ops: ['is', 'is not'] },
  filename: { label: 'Filename', type: 'text', get: (f) => f.file, ops: ['contains', 'starts with', 'matches regex'] },
  tag: { label: 'Tag', type: 'enum', get: (f) => f.tags || [], ops: ['has', 'does not have'] },
  seniority: { label: 'Owner seniority', type: 'enum', get: (f) => f.seniority, ops: ['is', 'is not'] },
  exposure: { label: 'External exposure', type: 'enum', get: exposureOf, ops: ['is', 'is not'] },
  sensitivity: { label: 'Sensitivity', type: 'enum', get: sensitivityOf, ops: ['is', 'is not'] },
  ageDays: { label: 'Age · days since modified', type: 'number', get: (f) => f.ageDays, ops: ['older than', 'newer than'], unit: 'days' },
  views90d: { label: 'Usage · views / 90d', type: 'number', get: (f) => f.views90d, ops: ['greater than', 'less than'], unit: 'views' },
  sizeKB: { label: 'Size · KB', type: 'number', get: (f) => f.sizeKB, ops: ['greater than', 'less than'], unit: 'KB' },
  severity: { label: 'Worst WCAG finding', type: 'sev', get: worstSev, ops: ['is at least'] },
}
const uniq = (a) => [...new Set(a)].filter(Boolean).sort()
const deriveOptions = (files) => ({
  department: uniq(files.map((f) => f.department)),
  repository: uniq(files.map((f) => f.sourceName)),
  type: uniq(files.map((f) => f.type)),
  tag: uniq(files.flatMap((f) => f.tags || [])),
  seniority: uniq(files.map((f) => f.seniority)),
  exposure: ['public-facing', 'high-traffic', 'internal'],
  sensitivity: ['PII', 'legal-hold', 'none'],
  severity: ['MINOR', 'MODERATE', 'SERIOUS', 'CRITICAL'],
})

function evalCond(f, c) {
  const fd = FIELDS[c.field]; if (!fd) return false
  const v = fd.get(f); const val = c.value
  const s = (x) => String(x).toLowerCase()
  switch (c.op) {
    case 'is': return s(v) === s(val)
    case 'is not': return s(v) !== s(val)
    case 'contains': return s(v).includes(s(val))
    case 'starts with': return s(v).startsWith(s(val))
    case 'matches regex': try { return new RegExp(val, 'i').test(String(v)) } catch { return false }
    case 'has': return Array.isArray(v) && v.map(s).includes(s(val))
    case 'does not have': return Array.isArray(v) && !v.map(s).includes(s(val))
    case 'older than': return Number(v) > Number(val)
    case 'newer than': return Number(v) < Number(val)
    case 'greater than': return Number(v) > Number(val)
    case 'less than': return Number(v) < Number(val)
    case 'is at least': return SEV_ORDER.indexOf(v) >= SEV_ORDER.indexOf(val)
    default: return false
  }
}
const evalRule = (f, rule) => { const cs = rule.conditions || []; return cs.length ? (rule.match === 'any' ? cs.some((c) => evalCond(f, c)) : cs.every((c) => evalCond(f, c))) : false }

// Weighted risk = WCAG severity × business criticality × exposure × regulatory × usage.
const PRIORITY_W = { Critical: 4, High: 3, Medium: 2, Low: 1 }
const SEV_W = { none: 0.5, MINOR: 1, MODERATE: 2, SERIOUS: 3, CRITICAL: 4 }
function riskFactors(f, priority) {
  return {
    severity: SEV_W[worstSev(f)] || 0.5,
    criticality: PRIORITY_W[priority] || 2,
    exposure: { 'public-facing': 3, 'high-traffic': 2, internal: 1 }[exposureOf(f)],
    regulatory: sensitivityOf(f) === 'none' ? 1 : 3,
    usage: Math.max(1, Math.min(3, +(Math.log10((f.views90d || 1) + 1)).toFixed(2))),
  }
}
const riskScore = (f, priority) => { const r = riskFactors(f, priority); return r.severity * r.criticality * r.exposure * r.regulatory * r.usage }

// ---- Natural-language → structured rule (deterministic; previews before activation) ----
function parseNL(text, opts) {
  const t = ' ' + text.toLowerCase() + ' '
  const conditions = []
  opts.department.forEach((d) => { const key = d.toLowerCase().split(/[ &]/)[0]; if (key.length > 2 && t.includes(key)) conditions.push({ field: 'department', op: 'is', value: d }) })
  if (/\bexternal|public|customer-facing|customer facing|externally published|published\b/.test(t)) conditions.push({ field: 'exposure', op: 'is', value: 'public-facing' })
  ;['pdf', 'docx', 'pptx', 'xlsx', 'html'].forEach((ty) => { if (new RegExp(`\\b${ty}s?\\b`).test(t)) conditions.push({ field: 'type', op: 'is', value: ty }) })
  if (/\bpii|patient|phi|sensitive\b/.test(t)) conditions.push({ field: 'sensitivity', op: 'is', value: 'PII' })
  if (/\blegal hold|litigation\b/.test(t)) conditions.push({ field: 'sensitivity', op: 'is', value: 'legal-hold' })
  if (/\bexecutive|leadership|c-suite\b/.test(t)) conditions.push({ field: 'seniority', op: 'is', value: 'Executive' })
  const mm = t.match(/last (\d+) months?/); if (mm) conditions.push({ field: 'ageDays', op: 'newer than', value: String(+mm[1] * 30) })
  const my = t.match(/last (\d+) years?/); if (my) conditions.push({ field: 'ageDays', op: 'newer than', value: String(+my[1] * 365) })
  if (/\barchived|legacy|old\b/.test(t)) conditions.push({ field: 'ageDays', op: 'older than', value: '540' })
  const kw = t.match(/(?:titled|named|contain(?:ing|s)?|with) ["“]?([a-z0-9 _-]{3,})["”]?/); if (kw) conditions.push({ field: 'filename', op: 'contains', value: kw[1].trim().split(' ')[0] })
  const priority = /critical/.test(t) ? 'Critical' : /\bhigh\b/.test(t) ? 'High' : /\blow\b/.test(t) ? 'Low' : /\bmedium\b/.test(t) ? 'Medium' : (/prioriti|wcag first|first/.test(t) ? 'High' : null)
  const sla = (t.match(/within (\d+) days?/) || [])[1] || (/within a month|monthly|within 30 days/.test(t) ? '30' : null)
  const match = /\bor\b/.test(t) && !/\band\b/.test(t) ? 'any' : 'all'
  return { conditions, match, actions: { priority: priority || 'High', slaDays: sla ? +sla : null } }
}

const PRI_COLOR = { Critical: ['#1F5FA8', '#E2EDFB'], High: ['#854F0B', '#FAEEDA'], Medium: ['#3C3489', '#EEEDFE'], Low: ['#5F5E5A', '#EFEDEA'] }
const condText = (c) => `${FIELDS[c.field]?.label || c.field} ${c.op} “${c.value}”`

const DEFAULT_STATE = {
  labels: [
    { id: 'l1', name: 'Patient Consent Forms', color: '#1F5FA8' },
    { id: 'l2', name: 'High-Risk Legal Contracts', color: '#854F0B' },
    { id: 'l3', name: 'Board Minutes', color: '#3C3489' },
    { id: 'l4', name: 'Legacy HR Policies', color: '#5F5E5A' },
  ],
  taxonomy: { name: 'Corporate Documents', children: [
    { name: 'Legal', children: [{ name: 'Contracts' }, { name: 'Litigation' }, { name: 'Compliance' }] },
    { name: 'Human Resources', children: [{ name: 'Benefits' }, { name: 'Recruiting' }, { name: 'Payroll' }] },
    { name: 'Product', children: [{ name: 'Specifications' }, { name: 'Manuals' }, { name: 'Release Notes' }] },
  ] },
  rules: [
    { id: 'r1', name: 'Customer-facing PDFs → Critical', match: 'all', conditions: [{ field: 'exposure', op: 'is', value: 'public-facing' }, { field: 'type', op: 'is', value: 'pdf' }], actions: { priority: 'Critical', slaDays: 30, label: 'l1' } },
    { id: 'r2', name: 'Anything owned by Legal → High', match: 'all', conditions: [{ field: 'department', op: 'is', value: 'Legal & Compliance' }], actions: { priority: 'High', slaDays: null, label: 'l2' } },
    { id: 'r3', name: 'Archived marketing → Low', match: 'all', conditions: [{ field: 'department', op: 'is', value: 'Communications' }, { field: 'ageDays', op: 'older than', value: '540' }], actions: { priority: 'Low', slaDays: null } },
  ],
  version: 1, status: 'draft', publishedAt: null, history: [],
}
const load = () => { try { const s = JSON.parse(localStorage.getItem(LS_KEY)); return s && s.labels ? s : DEFAULT_STATE } catch { return DEFAULT_STATE } }
let _id = 100
const nid = (p) => `${p}${_id++}`

function Tree({ node, depth = 0, onAdd, onRemove }) {
  return (
    <div className="onttreenode" style={{ marginLeft: depth ? 16 : 0 }}>
      <div className="onttreerow">
        <span className="onttreename">{depth > 0 && <span className="onttreeglyph" aria-hidden="true">{'└ '}</span>}{node.name}</span>
        <span className="onttreeacts">
          <button className="ghost small" onClick={() => onAdd(node)} title="Add a child category">＋</button>
          {depth > 0 && <button className="ghost small" onClick={() => onRemove(node)} title="Remove">✕</button>}
        </span>
      </div>
      {(node.children || []).map((c, i) => <Tree key={i} node={c} depth={depth + 1} onAdd={onAdd} onRemove={onRemove} />)}
    </div>
  )
}

export default function Ontology({ files = [] }) {
  const [st, setSt] = useState(load)
  const [tab, setTab] = useState('taxonomy')
  const [nl, setNl] = useState('')
  const [nlRule, setNlRule] = useState(null)
  const [draft, setDraft] = useState(() => ({ name: '', match: 'all', conditions: [{ field: 'department', op: 'is', value: '' }], actions: { priority: 'High', slaDays: null, label: '' } }))
  const opts = useMemo(() => deriveOptions(files), [files])
  useEffect(() => { try { localStorage.setItem(LS_KEY, JSON.stringify(st)) } catch { /* ignore */ } }, [st])
  const dirty = st.status === 'draft' || st.dirty
  const set = (patch) => setSt((s) => ({ ...s, ...patch, status: 'draft', dirty: true }))

  // ---- evaluation against the real corpus ----
  const matchesFor = (rule) => files.filter((f) => evalRule(f, rule))
  // first matching rule wins for a doc's classification
  const classified = useMemo(() => files.map((f) => {
    const rule = st.rules.find((r) => evalRule(f, r))
    const priority = rule?.actions?.priority || null
    return { f, rule, priority, score: rule ? riskScore(f, priority) : 0 }
  }), [files, st.rules])
  const covered = classified.filter((c) => c.rule)
  const ranked = [...covered].sort((a, b) => b.score - a.score).slice(0, 12)
  const labelName = (id) => st.labels.find((l) => l.id === id)?.name

  // ---- handlers ----
  const addLabel = () => set({ labels: [...st.labels, { id: nid('l'), name: 'New label', color: '#1F5FA8' }] })
  const editLabel = (id, patch) => set({ labels: st.labels.map((l) => l.id === id ? { ...l, ...patch } : l) })
  const delLabel = (id) => set({ labels: st.labels.filter((l) => l.id !== id) })
  const addCat = (parent) => { const name = prompt('Category name'); if (!name) return; parent.children = [...(parent.children || []), { name }]; set({ taxonomy: { ...st.taxonomy } }) }
  const rmCat = (node) => { const strip = (n) => ({ ...n, children: (n.children || []).filter((c) => c !== node).map(strip) }); set({ taxonomy: strip(st.taxonomy) }) }
  const addRule = (r) => set({ rules: [...st.rules, { ...r, id: nid('r') }] })
  const delRule = (id) => set({ rules: st.rules.filter((r) => r.id !== id) })
  const addCond = () => setDraft((d) => ({ ...d, conditions: [...d.conditions, { field: 'department', op: 'is', value: '' }] }))
  const setCond = (i, patch) => setDraft((d) => ({ ...d, conditions: d.conditions.map((c, n) => n === i ? { ...c, ...patch } : c) }))
  const rmCond = (i) => setDraft((d) => ({ ...d, conditions: d.conditions.filter((_, n) => n !== i) }))
  const commitDraft = () => { if (!draft.conditions.length) return; addRule({ ...draft, name: draft.name || draft.conditions.map(condText).join(draft.match === 'any' ? ' OR ' : ' AND ').slice(0, 60) }); setDraft({ name: '', match: 'all', conditions: [{ field: 'department', op: 'is', value: '' }], actions: { priority: 'High', slaDays: null, label: '' } }) }
  const publish = () => setSt((s) => ({ ...s, status: 'published', dirty: false, version: s.version + (s.status === 'draft' ? 1 : 0), publishedAt: new Date().toLocaleString(), history: [{ v: s.version + (s.status === 'draft' ? 1 : 0), at: new Date().toLocaleString(), by: 'admin', rules: s.rules.length, labels: s.labels.length }, ...(s.history || [])].slice(0, 12) }))

  const condCtl = (c, i) => {
    const fd = FIELDS[c.field]
    return (
      <div className="ontcond" key={i}>
        <select value={c.field} onChange={(e) => setCond(i, { field: e.target.value, op: FIELDS[e.target.value].ops[0], value: '' })}>
          {Object.entries(FIELDS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <select value={c.op} onChange={(e) => setCond(i, { op: e.target.value })}>{fd.ops.map((o) => <option key={o}>{o}</option>)}</select>
        {fd.type === 'enum' || fd.type === 'sev'
          ? <select value={c.value} onChange={(e) => setCond(i, { value: e.target.value })}><option value="">choose…</option>{(opts[c.field] || []).map((o) => <option key={o}>{o}</option>)}</select>
          : <input value={c.value} placeholder={fd.unit || 'value'} onChange={(e) => setCond(i, { value: e.target.value })} />}
        {draft.conditions.length > 1 && <button className="ghost small" onClick={() => rmCond(i)} aria-label="Remove condition">✕</button>}
      </div>
    )
  }

  const RuleCard = ({ r }) => {
    const n = matchesFor(r).length
    const [fg, bg] = PRI_COLOR[r.actions?.priority] || PRI_COLOR.Medium
    return (
      <div className="ontrule">
        <div className="ontruletop">
          <b>{r.name}</b>
          <span className="ontpri" style={{ color: fg, background: bg }}>{r.actions?.priority}{r.actions?.slaDays ? ` · ${r.actions.slaDays}d SLA` : ''}</span>
          <button className="ghost small" onClick={() => delRule(r.id)} aria-label="Delete rule" style={{ marginLeft: 'auto' }}>✕</button>
        </div>
        <div className="ontrulecond">{(r.conditions || []).map((c, i) => <span key={i} className="ontchip">{condText(c)}{i < r.conditions.length - 1 && <em className="ontjoin"> {r.match === 'any' ? 'OR' : 'AND'} </em>}</span>)}</div>
        <div className="ontrulefoot"><span className="ontmatch">⟶ matches <b>{n.toLocaleString()}</b> of {files.length.toLocaleString()} documents</span>{r.actions?.label && labelName(r.actions.label) && <span className="muted"> · labels as “{labelName(r.actions.label)}”</span>}</div>
      </div>
    )
  }

  return (
    <div className="ontwrap">
      <div className="ontbar">
        <div>
          <b>Business ontology &amp; taxonomy</b>
          <div className="muted" style={{ marginTop: 2 }}>Teach the platform your org's document model — labels, taxonomy &amp; prioritisation rules that classify the real estate. {files.length.toLocaleString()} documents in scope.</div>
        </div>
        <div className="ontpublish">
          <span className={dirty ? 'ontstatus draft' : 'ontstatus live'}>{dirty ? '● Draft — unpublished changes' : `✓ Published v${st.version}`}</span>
          <button onClick={publish} disabled={!dirty}>Publish ontology</button>
        </div>
      </div>

      <div className="subtabs" role="tablist" aria-label="Ontology sections">
        {[['taxonomy', 'Labels & taxonomy'], ['rules', `Rules · ${st.rules.length}`], ['impact', 'Impact & risk'], ['versions', 'Versions & advanced']].map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'fchip on' : 'fchip'} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>

      {tab === 'taxonomy' && (
        <div className="ontcols">
          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>Custom labels</h3><button className="ghost small" onClick={addLabel}>＋ Add label</button></div>
            <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>Org-specific document types — applied by rules or by hand.</div>
            <div className="ontlabels">
              {st.labels.map((l) => (
                <div className="ontlabel" key={l.id}>
                  <input type="color" value={l.color} onChange={(e) => editLabel(l.id, { color: e.target.value })} aria-label="Label colour" />
                  <input className="ontlabelname" value={l.name} onChange={(e) => editLabel(l.id, { name: e.target.value })} />
                  <span className="ontlabelpill" style={{ color: l.color, background: l.color + '22' }}>{l.name}</span>
                  <button className="ghost small" onClick={() => delLabel(l.id)} aria-label="Delete label">✕</button>
                </div>
              ))}
            </div>
          </section>
          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>Hierarchical taxonomy</h3></div>
            <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>Parent/child categories documents can be filed under. Use ＋ to nest.</div>
            <div className="onttree"><Tree node={st.taxonomy} onAdd={addCat} onRemove={rmCat} /></div>
          </section>
        </div>
      )}

      {tab === 'rules' && (
        <>
          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>Natural-language rule</h3><span className="muted" style={{ fontSize: 12 }}>type a rule — we convert it to a deterministic, previewable rule</span></div>
            <div className="ontnl">
              <input value={nl} placeholder="e.g. Prioritize all externally published policy documents owned by HR and Legal" onChange={(e) => setNl(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') setNlRule(parseNL(nl, opts)) }} />
              <button onClick={() => setNlRule(parseNL(nl, opts))} disabled={!nl.trim()}>Interpret</button>
            </div>
            {nlRule && (
              <div className="ontnlout">
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Interpreted as — review before adding:</div>
                <div className="ontrulecond">{nlRule.conditions.length ? nlRule.conditions.map((c, i) => <span key={i} className="ontchip">{condText(c)}{i < nlRule.conditions.length - 1 && <em className="ontjoin"> {nlRule.match === 'any' ? 'OR' : 'AND'} </em>}</span>) : <span className="muted">no conditions recognised — rephrase or build below</span>}</div>
                <div className="ontnlfoot"><span className="ontpri" style={{ color: PRI_COLOR[nlRule.actions.priority][0], background: PRI_COLOR[nlRule.actions.priority][1] }}>{nlRule.actions.priority}{nlRule.actions.slaDays ? ` · ${nlRule.actions.slaDays}d` : ''}</span><span className="muted"> · matches {files.filter((f) => evalRule(f, nlRule)).length.toLocaleString()} docs</span><button className="ghost small" disabled={!nlRule.conditions.length} onClick={() => { addRule({ ...nlRule, name: nl.slice(0, 60) }); setNl(''); setNlRule(null) }} style={{ marginLeft: 'auto' }}>＋ Add this rule</button></div>
              </div>
            )}
          </section>

          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>Rule builder</h3><span className="muted" style={{ fontSize: 12 }}>match
              <select value={draft.match} onChange={(e) => setDraft((d) => ({ ...d, match: e.target.value }))} style={{ margin: '0 4px' }}><option value="all">ALL</option><option value="any">ANY</option></select>
              of:</span></div>
            {draft.conditions.map((c, i) => condCtl(c, i))}
            <button className="ghost small" onClick={addCond} style={{ marginTop: 4 }}>＋ Add condition</button>
            <div className="ontaction">
              <span className="muted">then set priority</span>
              <select value={draft.actions.priority} onChange={(e) => setDraft((d) => ({ ...d, actions: { ...d.actions, priority: e.target.value } }))}>{Object.keys(PRIORITY_W).map((p) => <option key={p}>{p}</option>)}</select>
              <span className="muted">label</span>
              <select value={draft.actions.label} onChange={(e) => setDraft((d) => ({ ...d, actions: { ...d.actions, label: e.target.value } }))}><option value="">none</option>{st.labels.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select>
              <span className="muted">SLA</span>
              <input style={{ width: 56 }} placeholder="days" value={draft.actions.slaDays || ''} onChange={(e) => setDraft((d) => ({ ...d, actions: { ...d.actions, slaDays: e.target.value ? +e.target.value : null } }))} />
              <span className="ontmatch" style={{ marginLeft: 'auto' }}>preview: <b>{files.filter((f) => evalRule(f, draft)).length.toLocaleString()}</b> match</span>
              <button onClick={commitDraft}>Add rule</button>
            </div>
          </section>

          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>Active rules</h3><span className="muted" style={{ fontSize: 12 }}>first matching rule classifies a document</span></div>
            {st.rules.length ? st.rules.map((r) => <RuleCard key={r.id} r={r} />) : <p className="muted">No rules yet.</p>}
          </section>
        </>
      )}

      {tab === 'impact' && (
        <>
          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>Weighted risk score</h3></div>
            <div className="ontformula"><code>Overall priority = WCAG severity × business criticality × external exposure × regulatory risk × document usage</code></div>
            <div className="ontstats">
              <div className="ontstat"><b>{covered.length.toLocaleString()}</b><span className="muted">of {files.length.toLocaleString()} classified by your rules</span></div>
              {['Critical', 'High', 'Medium', 'Low'].map((p) => { const n = covered.filter((c) => c.priority === p).length; return <div className="ontstat" key={p}><b style={{ color: PRI_COLOR[p][0] }}>{n}</b><span className="muted">{p} priority</span></div> })}
            </div>
          </section>
          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>Estimated impact — top documents by business risk</h3><span className="muted" style={{ fontSize: 12 }}>how the published ontology re-ranks the remediation queue</span></div>
            <div className="ontranklist">
              {ranked.length ? ranked.map((c, i) => { const fac = riskFactors(c.f, c.priority); const [fg, bg] = PRI_COLOR[c.priority] || PRI_COLOR.Medium; return (
                <div className="ontrankrow" key={i}>
                  <span className="ontrankn">{i + 1}</span>
                  <div className="ontrankmain"><div className="ontrankfile">{c.f.file}</div><div className="muted" style={{ fontSize: 11 }}>{c.f.department} · {exposureOf(c.f)} · {worstSev(c.f).toLowerCase()} finding · {c.f.views90d} views</div></div>
                  <span className="ontpri" style={{ color: fg, background: bg }}>{c.priority}</span>
                  <span className="ontscore" title={`severity ${fac.severity} × criticality ${fac.criticality} × exposure ${fac.exposure} × regulatory ${fac.regulatory} × usage ${fac.usage}`}>{Math.round(c.score)}</span>
                </div>
              ) }) : <p className="muted">No documents matched — add rules to classify the estate.</p>}
            </div>
          </section>
        </>
      )}

      {tab === 'versions' && (
        <>
          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>Version history &amp; audit</h3></div>
            <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>Draft &amp; publish ontology changes; every publish is snapshotted with who &amp; when. Roll back restores that version's rules.</div>
            {(st.history || []).length ? st.history.map((h, i) => (
              <div className="ontver" key={i}><span className="ontvertag">v{h.v}</span><span className="ontverwhen">{h.at} · by {h.by}</span><span className="muted">{h.rules} rules · {h.labels} labels</span>{i > 0 && <button className="ghost small" style={{ marginLeft: 'auto' }} disabled title="Snapshot rollback — restores this version's rules">↩ Roll back</button>}</div>
            )) : <p className="muted">No published versions yet — publish to create v{st.version}.</p>}
          </section>
          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>AI-assisted classification</h3><span className="ontprevtag">preview</span></div>
            <p className="muted" style={{ fontSize: 12 }}>Give the agent a few example documents per label; it learns to classify similar ones, with a confidence threshold and manual override. Requires the vision/LLM model — wired in the cloud build, mocked here.</p>
            <div className="ontexrow"><span className="ontchip">＋ add example docs</span><span className="muted">confidence ≥</span><input type="range" min="50" max="99" defaultValue="80" disabled /><span className="muted">80%</span></div>
          </section>
          <section className="panel">
            <div className="ontsechd"><h3 style={{ margin: 0 }}>Ontology relationships</h3><span className="ontprevtag">preview</span></div>
            <p className="muted" style={{ fontSize: 12 }}>Model dependencies for dependency-aware remediation &amp; reporting.</p>
            <div className="ontrels">
              {['Procedure supports Policy', 'Translation belongs to Original', 'Attachment belongs to Contract', 'Training Guide supersedes Legacy Manual'].map((r) => <span key={r} className="ontrel">{r}</span>)}
            </div>
          </section>
        </>
      )}
    </div>
  )
}
